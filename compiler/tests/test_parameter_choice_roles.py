"""S26/W13: temporal roles bind an explicitly named parameter code, independently of its display name."""

import copy
import json
import shutil

import pytest
import yaml

from calcsupport import checked, connect, run_both
from rede_compiler import calc, calc_sql
from rede_compiler import pack
from rede_compiler.pack import CompileError, Kind, Slot
from test_calc import CHOICE, FIXTURE, PACK, choice_case


def role_case(*, knowledge=True, inherited=None):
    model = copy.deepcopy(PACK)
    doc, rows = choice_case()
    setting = model.kinds["setting"]
    rename = {"name": "code", "valid_from": "starts", "valid_until": "ends", "known_from": "recorded"}
    tables = {}
    for old, new in rename.items():
        slot = setting.slots.pop(old)
        tables[slot.table] = f"setting__{new}"
        slot.name = new
        if old != "name" and (old != "known_from" or knowledge):
            slot.role = old
        setting.slots[new] = slot
    # A display name can be different from the semantic parameter code used by a leaf.
    setting.slots["title"] = Slot("title", "setting", False, False, "string", "VARCHAR", names=True, role="name")
    if inherited:
        parent = Kind("window", "Window", "facts", None, False, "id")
        model.kinds[parent.name] = parent
        setting.parent = parent.name
        names = ["starts", "ends", "recorded"] if inherited == "dates" else ["value"]
        for name in names:
            slot = setting.slots.pop(name)
            old_table = slot.table
            slot.kind = parent.name
            parent.slots[name] = slot
            for original, renamed in list(tables.items()):
                if renamed == old_table:
                    tables[original] = slot.table
            tables[old_table] = slot.table
        rows["window"] = list(rows["setting"])
    rows = {tables.get(table, table): values for table, values in rows.items()}
    rows["setting__title"] = [(e, "Display " + e) for (e,) in rows["setting"]]
    doc["parameter_choice"] = {"name": "code"}
    return model, doc, rows


@pytest.mark.parametrize("inherited", [None, "dates", "value"])
def test_short_binding_uses_roles_including_inherited_slots(inherited):
    model, doc, rows = role_case(inherited=inherited)
    prog = calc.build(model, doc)
    got, want = run_both(model, prog, doc, rows)
    assert got == want
    assert got["rate"]["i0"][:2] == ("known", "21")
    assert got["late"]["i0"][:2] == ("unknown", "")
    ir = calc.to_doc(prog)["parameter_choice"]
    assert ir["name"] == "setting__code"  # not the rdfs:label display title
    prefix = "window" if inherited == "dates" else "setting"
    assert ir["valid_from"] == f"{prefix}__starts" and ir["known_from"] == f"{prefix}__recorded"
    if inherited != "value":
        explicit = dict(doc, parameter_choice={r: {"name": "code", "valid_from": "starts", "valid_until": "ends",
                                                  "known_from": "recorded"}[r] for r in CHOICE})
        old = calc.build(model, explicit)
        assert calc.to_doc(prog) == calc.to_doc(old)
        assert calc_sql.choice_sql(prog) == calc_sql.choice_sql(old)


def no_knowledge_case():
    model, doc, rows = role_case(knowledge=False)
    # Two overlapping valid rows: the latest valid-from wins even if an ordinary, unbound recorded
    # date says it lies in the future. No knowledge role means known from the start, not a fake date.
    remove = {"rate-2026-fix", "rate-2026-next"}
    rows = {t: [r for r in rs if r[0] not in remove] for t, rs in rows.items()}
    rows["setting__ends"] = [(e, "2027-01-01" if e == "rate-2025" else v) for e, v in rows["setting__ends"]]
    rows["setting__recorded"] = [(e, "2026-12-01" if e == "rate-2026" else v)
                                  for e, v in rows["setting__recorded"]]
    return model, doc, rows


def test_without_a_knowledge_role_all_rows_are_known_from_the_start():
    model, doc, rows = no_knowledge_case()
    prog = calc.build(model, doc)
    got, want = run_both(model, prog, doc, rows)
    assert got == want
    assert {r: values["i0"][:2] for r, values in got.items()} == {
        "rate": ("known", "20"), "late": ("known", "5"), "gone": ("unknown", ""),
        "tie": ("invalid", ""), "absent": ("unknown", "")}
    assert "known_from" not in calc.to_doc(prog)["parameter_choice"]
    ws = calc_sql.witnesses(connect(model, prog, rows), prog)
    selected = next(w for w in ws if w["conclusion"]["relation"] == "calc__rate"
                    and json.loads(w["conclusion"]["key"])[0] == "i0")
    assert selected["steps"][0]["element"] == "rate-2026"
    assert "setting__recorded" not in selected["reads"]
    assert {"setting__starts", "setting__ends", "setting__code"} <= set(selected["reads"])


def test_a_declared_knowledge_role_with_a_missing_value_stays_missing():
    model, doc, rows = role_case()
    rows["setting__recorded"] = [(e, v) for e, v in rows["setting__recorded"] if e != "late"]
    got, want = run_both(model, calc.build(model, doc), doc, rows)
    assert got == want and got["late"]["i0"][:3] == ("unknown", "", "parameter late is missing")


def test_equal_latest_values_keep_the_smallest_element_id_without_knowledge_time():
    model, doc, rows = no_knowledge_case()
    rows["setting__value"] = [(e, 1 if e == "tie-b" else v) for e, v in rows["setting__value"]]
    prog = calc.build(model, doc)
    got, want = run_both(model, prog, doc, rows)
    assert got == want and got["tie"]["i0"][:2] == ("known", "1")
    ws = calc_sql.witnesses(connect(model, prog, rows), prog)
    assert next(w for w in ws if w["conclusion"]["relation"] == "calc__tie")["steps"][0]["element"] == "tie-a"


def test_the_checker_refuses_a_forged_chosen_element_without_knowledge_time():
    model, doc, rows = no_knowledge_case()
    prog = calc.build(model, doc)
    db = connect(model, prog, rows)
    ws = calc_sql.witnesses(db, prog)
    next(w for w in ws if w["conclusion"]["relation"] == "calc__rate")["steps"][0]["element"] = "rate-2025"
    assert any(f["reason"] == "calc_leaf" for f in checked(db, prog, ws))


@pytest.mark.parametrize("bad", ["missing", "duplicate", "wrong_type", "datetime", "multivalued"])
def test_short_bindings_refuse_missing_ambiguous_or_untyped_roles(bad):
    model, doc, _ = role_case()
    slot = model.kinds["setting"].slots["starts"]
    if bad == "missing":
        slot.role = None
    elif bad == "duplicate":
        other = copy.copy(slot)
        other.name = "another_start"
        model.kinds["setting"].slots[other.name] = other
    elif bad == "multivalued":
        slot.multivalued = True
    else:
        slot.sql_type = "VARCHAR" if bad == "wrong_type" else "TIMESTAMP"
    with pytest.raises(CompileError, match="calc.binding: parameter_choice"):
        calc.build(model, doc)


def test_no_choice_binding_keeps_legacy_id_lookup_even_when_roles_exist():
    model, doc, rows = role_case()
    del doc["parameter_choice"]
    got, want = run_both(model, calc.build(model, doc), doc, rows)
    assert got == want
    assert got["rate"]["i0"][:2] == ("unknown", "")  # rate is a code, not any of the row ids


@pytest.mark.parametrize("knowledge", [False, True])
def test_a_written_short_binding_reads_the_schema_roles(tmp_path, knowledge):
    directory = shutil.copytree(FIXTURE, tmp_path / "pack")
    path = directory / "schema" / "calc.yaml"
    schema = yaml.safe_load(path.read_text())
    schema["prefixes"] = {"schema": "https://schema.org/", "prov": "http://www.w3.org/ns/prov#"}
    slots = schema["classes"]["Setting"]["attributes"]
    slots["valid_from"]["slot_uri"] = "schema:validFrom"
    slots["valid_until"]["slot_uri"] = "schema:validThrough"
    if knowledge:
        slots["known_from"]["slot_uri"] = "prov:generatedAtTime"
    path.write_text(yaml.safe_dump(schema, sort_keys=False))
    doc, rows = choice_case()
    doc["parameter_choice"] = {"name": "name"}
    (directory / "calc" / "example.yaml").write_text(yaml.safe_dump(doc, sort_keys=False))
    model = pack.read(directory)
    prog = calc.build(model, model.calc)
    got, want = run_both(model, prog, model.calc, rows)
    assert got == want
    assert got["late"]["i0"][:2] == (("unknown", "") if knowledge else ("known", "5"))
    assert ("known_from" in calc.to_doc(prog)["parameter_choice"]) is knowledge
