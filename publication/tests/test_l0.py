"""The L0 reader and verifier against every settled conformance case of docs/publication/l0.md §8.

Each case file names what it expects; this test also fixes *why* a case is rejected (`REJECTED_FOR`), so a
rejection for another reason fails. Cases that need the Arrow, Parquet or RDF forms run with those forms.
"""

import copy
import json
from pathlib import Path

import jsonschema
import pytest
import yaml

from rezono_canon import canonical_json, canonical_sha256

from rezono_publication import l0
from rezono_publication.hash import hash_rows, hashes

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "docs" / "publication" / "cases"
FIXTURE = json.loads((CASES / "fixture.schema.json").read_text("utf-8"))
FILES = {p.stem: yaml.safe_load(p.read_text("utf-8")) for p in sorted(CASES.glob("[A-Z][0-9][0-9].yaml"))}

# What each rejection must be about: a fragment of the reader's error text.
REJECTED_FOR = {
    "S03": "integer must be text",
    "S04": "not in code order",
    "S05": "full schema id",
    "S06": "shares its IRI with `Host`",
    "R02": "a Quantity is text",
    "R03": "not the shortest exact decimal",
    "R05": "is a JSON number (LD2)",
    "R06": ["12.0 is not an integer", "1e1 is not an integer", "-0 is not an integer"],  # per text
    "R07": "null",
    "R08": "state `not_applicable` not allowed",
    "R09": "state `unknown` not allowed",
    "R10": "every slot is present",
    "R11": "duplicate member",
    "R12": "two rows with one `$kind` and `$id`",
    "R13": "pack and schema differ from the import",
    "R14": ["duplicate key", "lone surrogate"],  # per text
    "R16": "undefined $-member `$version`",
    "V01": "`Host` is not versioned",
    "V03": "closed range in `$valid.at`",
    "V04": "axis `during` not declared",
    "V05": "empty `$valid` must be omitted",
    "V06": "`$known` missing; `known` is declared",
    "V07": "`versioned` not supported by this reader",
    "N01": "is not a reason code",
    "N02": "reason code `not_assigned` not declared",
    "N04": "`not_assigned` may not label `not_applicable`",
    "P02": "epoch pin without hash pin",
    "P03": "`manifest` without `dataset`",
    "P04": "hash pin differs from the import",
    "A02": "extension metadata `scale` differs from the schema",
    "A03": "storage scale 4 differs from the schema's scale 2",
    "G02": "a data-plane kind omits it",
    "G03": "a control kind declares `owner`",
    "G05": "names no reviewed proposal",
}
CHANGE_FOR = {"M02": "added slot without `backfill`", "M08": "LD2 spelling change"}
# Settled cases this module does not run, and where they run.
ELSEWHERE = {
    "H06": "test_hash.py",
    "X02": "test_rdf.py (JSON-LD processing; X01's expansion runs there too)",
}


class MissingCase(KeyError):
    """An expected public case file is absent."""


def required_case(cid):
    if cid not in FILES:
        raise MissingCase(cid)
    return FILES[cid]


def merge(target, patch):
    """RFC 7396 JSON merge patch."""
    if not isinstance(patch, dict):
        return copy.deepcopy(patch)
    out = copy.deepcopy(target) if isinstance(target, dict) else {}
    for k, v in patch.items():
        if v is None:
            out.pop(k, None)
        else:
            out[k] = merge(out.get(k), v)
    return out


def schema_of(case) -> dict:
    return merge(FIXTURE, case["schema"].get("merge", {}))


R01 = FILES["R01"]["input"]["$rows"]


def rows_of(case):
    """The case's input as a list of rows; a text naming R01 is the collection of §3.1."""
    form, value = case["form"], case.get("input")
    if isinstance(value, str) and value.startswith("R01"):
        return R01
    if form == "row":
        return [value]
    if form == "rows":
        return value
    if form == "collection":
        return value["$rows"]
    raise AssertionError(f"no rows in form {form}")


class JsonTextErrors(l0.L0Error):
    """The errors of a list of texts, one per text, in order."""

    def __init__(self, errors):
        super().__init__(" | ".join(errors))
        self.errors = errors


def with_schema_id(schema, doc):
    """A case file MAY leave out a collection's `$schema`: the case's schema stands in for it (cases/schema.json)."""
    return {"$schema": l0.schema_id(schema), **doc} if isinstance(doc, dict) and "$schema" not in doc else doc


def run(case):
    """Read the case's input the way its form says; raise `L0Error` on a rejection."""
    schema, form, value = schema_of(case), case["form"], case.get("input")
    if form == "schema":
        return l0.check_schema(schema, versioned=case["id"] != "V07")
    l0.check_schema(schema)
    if form == "schema-text":
        return l0.check_schema(l0.loads(value))
    if form in ("row", "rows"):
        return l0.read_rows(schema, rows_of(case))
    if form == "collection":
        doc = value if isinstance(value, dict) else {"$rows": rows_of(case)}
        return l0.read_collection(schema, with_schema_id(schema, doc))
    if form == "json-text":
        errors = []
        for text in value:  # each text is read on its own; each must be rejected
            with pytest.raises(l0.L0Error) as e:
                l0.read_collection(schema, with_schema_id(schema, l0.loads(text)))
            errors.append(str(e.value))
        raise JsonTextErrors(errors)
    if form == "jsonl":
        return l0.read_jsonl(schema, value)
    if form == "arrow-field":
        return l0.check_field(schema, "Host", value)
    if form == "parquet-metadata":
        meta = dict(value["rezono"], schema=l0.schema_id(schema))
        return l0.check_table_metadata(schema, meta)
    if form == "delta":
        reviewed = set(value["reviewed"])
        return l0.admit(schema, value["delta"], reviewed.__contains__)
    raise AssertionError(f"form {form} is not run here")


SETTLED = sorted(i for i, c in FILES.items() if c["status"] == "settled" and i not in ELSEWHERE)


def test_every_case_file_is_a_valid_case():
    envelope = json.loads((CASES / "schema.json").read_text("utf-8"))
    jsonschema.Draft202012Validator.check_schema(envelope)
    validator = jsonschema.Draft202012Validator(envelope)
    for i, case in FILES.items():
        validator.validate(case)
        assert case["id"] == i
    case = FILES["R01"]
    for member in ("id", "class", "status", "schema", "form", "expect"):
        assert not validator.is_valid({k: v for k, v in case.items() if k != member}), member
    assert not validator.is_valid({**case, "exepct": case["expect"]})
    assert not validator.is_valid({**case, "expect": {"accept": "true"}})


@pytest.mark.xfail(strict=True, raises=MissingCase, reason=(
    "Needs settled S05, R13, P02 and P04 in docs/publication/cases. See decisions/publication-case-pins.md."
))
def test_every_settled_case_runs_here_or_is_named():
    runnable = {"valid", "invalid", "change", "hash", "context", "admission"}
    assert {i for i in SETTLED if FILES[i]["class"] not in runnable} == set()
    for i in sorted(REJECTED_FOR.keys() & FILES.keys()):
        case = FILES[i]
        assert case["expect"].get("accept") is False, i
        assert i in SETTLED and case["class"] in {"invalid", "admission", "context"}, i
    missing = sorted(REJECTED_FOR.keys() - FILES.keys())
    if missing:
        raise MissingCase(", ".join(missing))


@pytest.mark.parametrize("cid", [i for i in SETTLED if FILES[i]["class"] in ("valid", "invalid", "context",
                                                                            "admission")])
def test_accept_or_reject(cid):
    case = FILES[cid]
    if case["expect"]["accept"]:
        run(case)
        return
    with pytest.raises(l0.L0Error) as e:
        run(case)
    fragments = REJECTED_FOR[cid]
    if isinstance(fragments, list):  # one fragment per text, each pinned to its own text
        assert len(e.value.errors) == len(fragments), cid
        for fragment, error in zip(fragments, e.value.errors):
            assert fragment in error, f"{cid}: a text rejected for another reason: {error}"
        return
    assert fragments in str(e.value), f"{cid}: rejected for another reason: {e.value}"


@pytest.mark.parametrize("cid", [i for i in SETTLED if FILES[i]["class"] == "change"])
def test_change_class(cid):
    case = FILES[cid]
    a = schema_of(case)
    b = merge(a, case["successor"]["merge"])
    cls, why = l0.classify(a, b, datasets=[R01])
    assert cls == case["expect"]["change_class"], why
    if cid in CHANGE_FOR:
        assert any(CHANGE_FOR[cid] in w for w in why), why
    if "read_old_rows" in case["expect"]:
        read = {r["$id"]: r for r in l0.read_under(a, b, R01)}
        for rid, slots in case["expect"]["read_old_rows"].items():
            for slot, value in slots.items():
                assert read[rid][slot] == value


def test_s01_s02_schema_id():
    assert l0.check_schema(FIXTURE) == FILES["S01"]["expect"]["schema_id"]
    assert run(FILES["S02"]) == FILES["S02"]["expect"]["schema_id"]


def test_v02_two_versions_and_their_hash_keys():
    case = FILES["V02"]
    keys = [r["$key"] for r in hash_rows(schema_of(case), case["input"])["Plan"]]
    assert keys == case["expect"]["hash_keys"]
    assert len(keys) == case["expect"]["versions"]


def test_p01_the_pin_lives_in_the_import():
    case = required_case("P01")
    assert case["status"] == "settled" and case["class"] == "valid" and case["form"] == "row"
    assert case["expect"]["accept"] is True
    schema = schema_of(case)
    alias, kind = schema["kinds"]["Host"]["slots"]["zone"]["ref"].split(".")
    pin = schema["imports"][alias]
    assert set(pin) == {"pack", "schema", "manifest", "dataset"}
    assert kind == "Zone"
    assert case["expect"]["arrow_ref_metadata"] == {"kind": kind, **pin}
    assert case["expect"]["payload"]["zone"] == "dmz"
    target = f"{pin['pack']}@{pin['schema']}@{pin['manifest']}@{pin['dataset']}:Zone/dmz"
    assert case["input"]["zone"] == {"$ref": target}
    assert hash_rows(schema, [case["input"]])["Host"][0]["zone"] == case["expect"]["payload"]["zone"]
    field = {"name": "zone", "storage": "string",
             "extension": {"name": "rezono.ref", "metadata": case["expect"]["arrow_ref_metadata"]}}
    l0.check_field(schema, "Host", {**field, "storage": "utf8"})


def test_r15_jsonl_equals_r01():
    assert l0.read_jsonl(FIXTURE, FILES["R15"]["input"]) == R01


def test_g01_plane_is_in_the_schema_id():
    schema = schema_of(FILES["G01"])
    without = copy.deepcopy(schema)
    for member in ("plane", "owner"):
        del without["kinds"]["ZoneRule"][member]
    assert l0.check_schema(schema) != l0.check_schema(without)


def test_g03_a_control_kind_needs_a_decision_slot():
    schema = schema_of(FILES["G01"])
    for change in ({"decision": None}, {"decision": {"card": "?", "type": "Text", "states": ["known"]}},
                   {"decision": {"card": "1", "type": "Text", "states": ["known", "unknown"]}}):
        bad = merge(schema, {"kinds": {"ZoneRule": {"slots": change}}})
        with pytest.raises(l0.L0Error, match="slot `decision`"):
            l0.check_schema(bad)


def test_g04_definition_hash_covers_only_control_kinds():
    case = FILES["G04"]
    schema = schema_of(case)
    first, second = (hashes(schema, rows) for rows in case["input"])
    assert first["definition"] == second["definition"]
    assert first["dataset"] != second["dataset"]
    changed_rule = [dict(case["input"][0][0], allowed=True), case["input"][0][1]]
    assert hashes(schema, changed_rule)["definition"] != first["definition"]
    assert hashes(FIXTURE, R01)["definition"] == "c-" + canonical_sha256(
        {"schema": l0.schema_id(FIXTURE), "tables": {}})


def test_g05_admission_accepts_a_reviewed_decision_and_any_data_row():
    case = FILES["G05"]
    schema = schema_of(case)
    reviewed = set(case["input"]["reviewed"]).__contains__
    rule = dict(case["input"]["delta"][0], decision="prop-412")
    assert l0.admit(schema, [rule], reviewed) == [rule]
    assert l0.admit(schema, list(R01), lambda _: False) == R01  # a data-plane delta needs no review
    with pytest.raises(l0.L0Error, match="undefined"):
        l0.admit(schema, [dict(rule, **{"$version": "1"})], reviewed)  # admission is a full reader


# Normal forms beyond the case files (§3.2), on a schema with every core type.
TYPES = merge(FIXTURE, {
    "types": {
        "Price": {"of": "Money", "currency": "EUR", "scale": "2"},
        "Rate": {"of": "Money", "currency": "EUR", "scale": "4", "per": "h"},
        "Share": {"of": "Ratio", "min": "0", "max": "1"},
        "Window": {"of": "Period", "over": "Date", "range": "half_open"},
        "Size": {"of": "Enum", "enum": "Sizes"},
        "Code": {"of": "Text", "pattern": "[A-Z]{3}", "normalize": ["uppercase", "trim"]},
        "Big": {"of": "Integer", "min": "0", "max": "100000000000000000000"},
    },
    "enums": {"Sizes": ["s", "m", "l"]},
    "kinds": {"Thing": {"world": "closed", "id": {"type": "Text"}, "slots": {
        "price": {"card": "1", "type": "Price", "states": ["known"]},
        "rate": {"card": "1", "type": "Rate", "states": ["known"]},
        "share": {"card": "1", "type": "Share", "states": ["known"]},
        "window": {"card": "1", "type": "Window", "states": ["known"]},
        "size": {"card": "1", "type": "Size", "states": ["known"]},
        "code": {"card": "1", "type": "Code", "states": ["known"]},
        "big": {"card": "1", "type": "Big", "states": ["known"]},
        "seen": {"card": "1", "type": "DateTime", "states": ["known"]},
        "on": {"card": "1", "type": "Bool", "states": ["known"]},
        "hosts": {"card": "+", "ref": "Host", "states": ["known"]},
    }}},
})
THING = {"$kind": "Thing", "$id": "t", "price": "€ 12.30", "rate": "€ 0.1740/h", "share": "1/3",
         "window": "2026-11-01..<2026-12-01", "size": "m", "code": "ABC", "big": "12345678901234567890",
         "seen": "2026-11-09T07:40:00.5Z", "on": True, "hosts": [{"$ref": "host-a"}]}


def test_every_core_type_in_normal_form_is_read():
    l0.check_schema(TYPES)
    l0.read_row(TYPES, THING)


@pytest.mark.parametrize("slot, value, fragment", [
    ("price", "€ 12.3", "2 decimals"),
    ("price", "USD 12.30", "currency is not EUR"),
    ("rate", "€ 0.1740", "4 decimals"),
    ("share", "2/6", "lowest terms"),
    ("share", "3/2", "outside"),
    ("share", "1/1", "lowest terms"),
    ("window", "2026-11-01..2026-12-01", "half-open"),
    ("window", "2026-12-01..<2026-11-01", "ends before it starts"),
    ("size", "xl", "closed enum"),
    ("code", "abc", "normal form"),
    ("code", "ABCD", "pattern"),
    ("big", 12, "is text (LD2)"),
    ("seen", "2026-11-09T07:40:00.50Z", "normal form"),
    ("seen", "2026-11-09T07:40:00+01:00", "normal form"),
    ("on", "true", "not a boolean"),
    ("hosts", [], "at least one member"),
    ("hosts", ["host-a"], "not a reference"),
])
def test_a_value_not_in_normal_form_is_rejected(slot, value, fragment):
    with pytest.raises(l0.L0Error) as e:
        l0.read_row(TYPES, dict(THING, **{slot: value}))
    assert fragment in str(e.value), e.value


def test_a_python_float_is_never_read():
    with pytest.raises(l0.L0Error, match="float"):
        l0.read_row(merge(FIXTURE, json.loads(json.dumps(FILES["R04"]["schema"]["merge"]))),
                    dict(R01[0], count=12.0))


SOURCE_A = {"kind": "pack", "name": "facts/hosts.yaml", "position": "host-a"}
SOURCE_B = {"kind": "tool", "name": "inventory", "position": "2026-11-09"}


def test_src_is_sorted_and_names_slots():
    row = dict(FILES["R04"]["input"], **{"$src": {"memory_need": [SOURCE_B, SOURCE_A]}})
    schema = schema_of(FILES["R04"])
    with pytest.raises(l0.L0Error, match="sorted by canonical JSON"):
        l0.read_row(schema, row)
    row["$src"]["memory_need"].sort(key=canonical_json)
    l0.read_row(schema, row)
    with pytest.raises(l0.L0Error, match="not a slot"):
        l0.read_row(schema, dict(row, **{"$why": {"colour": "rezono:w/1"}}))


def test_loads_refuses_what_json_would_accept():
    for text, fragment in (('﻿{"a": "b"}', "byte order mark"), ('{"a": null}', "null"),
                           ('{"a": "x", "a": "y"}', "duplicate key"), ('{"a": NaN}', "not an integer"),
                           ('{"a": -0}', "-0"), ('{"a": "\\udc00"}', "lone surrogate")):
        with pytest.raises(l0.L0Error) as e:
            l0.loads(text)
        assert fragment in str(e.value), (text, e.value)
    assert l0.loads('{"a": "-0", "b": -10}') == {"a": "-0", "b": -10}


def test_change_classes_beyond_the_files():
    a = FIXTURE
    assert l0.classify(a, a) == ("patch", [])
    assert l0.classify(a, merge(a, {"map": {"Host": "https://schema.org/Thing"}}))[0] == "patch"
    assert l0.classify(a, merge(a, {"kinds": {"Zone": {"world": "open", "id": {"type": "Text"},
                                                       "slots": {}}}}))[0] == "minor"
    assert l0.classify(a, merge(a, {"base": "https://rezono.example/other/"}))[0] == "major"
    assert l0.classify(a, merge(a, {"kinds": {"Host": {"slots": {"owner": {"card": "1"}}}}}))[0] == "major"
    control = schema_of(FILES["G01"])
    assert l0.classify(control, merge(control, {"kinds": {"ZoneRule": {"owner": "platform"}}}))[0] == "patch"
    data_plane = merge(control, {"kinds": {"ZoneRule": {"plane": None, "owner": None}}})
    assert l0.classify(control, data_plane) == ("major", ["`ZoneRule.owner` changed", "`ZoneRule.plane` changed"])


def test_check_table_metadata():
    sid = l0.schema_id(FIXTURE)
    l0.check_table_metadata(FIXTURE, {"rezono": "1.0", "schema": sid, "table": "Host__tags", "role": "relation"})
    l0.check_table_metadata(FIXTURE, {"rezono": "1.0", "schema": sid, "table": "$why", "role": "why"})
    for bad, fragment in (({"table": "Host__owner", "role": "relation"}, "not a relation table"),
                          ({"table": "Host", "role": "kind", "plane": "control"}, "`plane`"),
                          ({"table": "Host", "role": "kind", "schema": "s-" + "a" * 64}, "`schema`")):
        with pytest.raises(l0.L0Error) as e:
            l0.check_table_metadata(FIXTURE, {"rezono": "1.0", "schema": sid, **bad})
        assert fragment in str(e.value)


def test_a_float_column_is_rejected():
    with pytest.raises(l0.L0Error, match="floating-point"):
        l0.check_field(FIXTURE, "Host", {"name": "memory_need", "storage": "double"})


# Each invalid input below names the rule that requires its refusal.
G = schema_of(FILES["G01"])
RULE = {"$kind": "ZoneRule", "$id": "r", "decision": "prop-412", "allowed": False}


def refused(fragment, call, *args):
    with pytest.raises(l0.L0Error) as e:
        call(*args)
    assert fragment in str(e.value), e.value


def test_p1_1_admission_checks_the_schema_itself():
    l0.admit(G, [RULE], {"prop-412"}.__contains__)
    asked = []
    for marker in ("Control", "control "):
        bad = merge(G, {"kinds": {"ZoneRule": {"plane": marker}}})
        refused("`plane` is only ever", l0.admit, bad, [dict(RULE, decision="unreviewed")], asked.append)
    no_owner = merge(G, {"kinds": {"ZoneRule": {"owner": None}}})
    refused("declares `owner`", l0.admit, no_owner, [RULE], lambda _: True)
    wide = merge(G, {"kinds": {"ZoneRule": {"slots": {"decision": {"states": ["known", "unknown"]}}}}})
    refused("slot `decision`", l0.admit, wide, [dict(RULE, decision={"$unknown": ""})], asked.append)
    assert asked == []  # `reviewed` is never asked under a schema that is not one


def test_p1_1_review_must_say_true():
    for answer in ("not reviewed", 1, {"ok": True}):
        refused("names no reviewed proposal", l0.admit, G, [RULE], lambda _, a=answer: a)
    refused("an empty `decision`", l0.admit, G, [dict(RULE, decision="")], lambda _: True)


def test_dv1_a_decision_may_be_a_reference_to_the_kind_that_records_decisions():
    # Rezono's packs record a decision as a row of std-decision, so a control kind's `decision` points to it.
    schema = merge(G, {"kinds": {"Decision": {"world": "closed", "id": {"type": "Text"}, "slots": {}},
                                 "ZoneRule": {"slots": {"decision": {"type": None, "ref": "Decision"}}}}})
    l0.check_schema(schema)
    asked = []
    row = dict(RULE, decision={"$ref": "prop-412"})
    assert l0.admit(schema, [row], lambda d: asked.append(d) or True) == [row]
    assert asked == ["prop-412"], "a reference names the decision by the id it points to"
    refused("names no reviewed proposal", l0.admit, schema, [row], lambda _: False)
    loose = merge(schema, {"kinds": {"ZoneRule": {"slots": {"decision": {"card": "?"}}}}})
    refused("slot `decision`", l0.check_schema, loose)


def test_p1_2_negative_zero_after_an_escaped_quote():
    refused("-0", l0.loads, '{"a": "x\\"y", "b": -0}')
    refused("-0", l0.loads, '{"$kind": "Item", "$id": "\\"", "n": -0}')
    refused("-0", l0.loads, '{"a": "x\\\\", "b": -0}')  # an escaped backslash ends no string early
    assert l0.loads('{"a": "x\\" -0 "}') == {"a": 'x" -0 '}
    assert l0.loads('{"a": "srv\\"", "b": "srv-0"}') == {"a": 'srv"', "b": "srv-0"}


@pytest.mark.parametrize("price", ["$ 12.30", "! 12.30", "USD 12.30", "¥ 12.30", "€€ 12.30"])
def test_p1_3_a_wrong_currency_is_refused(price):
    refused("currency is not EUR", l0.read_row, TYPES, dict(THING, price=price))


def test_p1_3_the_code_and_its_own_sign_are_read():
    for price in ("€ 12.30", "EUR 12.30"):
        l0.read_row(TYPES, dict(THING, price=price))


def test_p1_4_money_holds_the_slot_bounds():
    capped = merge(TYPES, {"kinds": {"Thing": {"slots": {"price": {"max": "10"}}}}})
    l0.check_schema(capped)
    refused("outside", l0.read_row, capped, THING)
    l0.read_row(capped, dict(THING, price="€ 9.99"))


@pytest.mark.parametrize("id_type, bad, good", [
    ("Date", "not-a-date", "2026-11-11"),
    ("Integer", "007", "7"),
    ("DateTime", "2026-11-11T10:00:00+01:00", "2026-11-11T09:00:00Z"),
])
def test_p1_5_an_id_is_read_in_its_type(id_type, bad, good):
    schema = merge(FIXTURE, {"kinds": {"Team": {"id": {"type": id_type}}}})
    l0.check_schema(schema)
    refused("$id", l0.read_row, schema, {"$kind": "Team", "$id": bad})
    l0.read_row(schema, {"$kind": "Team", "$id": good})


def test_p1_5_a_bool_is_no_id_type():
    refused("no id type", l0.check_schema, merge(FIXTURE, {"kinds": {"Team": {"id": {"type": "Bool"}}}}))


@pytest.mark.parametrize("change, fragment", [
    ({"@context": None}, "null"),
    ({"$id": "\ud800"}, "lone surrogate"),
    ({"tags": ["\ud800"]}, "lone surrogate"),
    ({"@context": 9007199254740992}, "JSON number outside an LD2 slot"),
    ({"@context": [{"@version": 2}]}, "JSON number outside an LD2 slot"),
])
def test_p1_6_the_object_entry_points_are_strict(change, fragment):
    refused(fragment, l0.read_row, FIXTURE, dict(R01[0], **change))


def test_p1_6_a_collection_is_strict_and_names_its_schema():
    sid = l0.schema_id(FIXTURE)
    refused("null", l0.read_collection, FIXTURE, {"$schema": None, "$rows": []})
    refused("full schema id", l0.read_collection, FIXTURE, {"$schema": "s-4be1", "$rows": []})
    refused("a collection is", l0.read_collection, FIXTURE, {"$rows": []})
    refused("null", l0.read_collection, FIXTURE, {"$schema": sid, "@context": None, "$rows": []})
    assert l0.read_collection(FIXTURE, {"$schema": sid, "$rows": []}) == []


def test_an_imported_type_is_refused_not_read_as_any_text():
    schema = merge(FIXTURE, {"imports": {"p": {"pack": "other", "schema": "s-" + "a" * 64}},
                             "kinds": {"Host": {"slots": {"code": {"card": "1", "type": "p.Code",
                                                                  "states": ["known", "unknown"]}}}}})
    l0.check_schema(schema)
    refused("cannot be checked without its schema (Q19)", l0.read_row, schema, dict(R01[0], code="abc"))
    l0.read_row(schema, dict(R01[0], code={"$unknown": ""}))  # a state needs no type


@pytest.mark.parametrize("sources, fragment", [
    ([{}], "a Source has `kind`, `name` and `position`"),
    ([{"a": "1"}], "members are those of a Source"),
    ([{"kind": "pack", "name": "f"}], "`kind`, `name` and `position`"),
    ([{"kind": "git", "name": "repo", "position": "a.yaml"}], "pins its `revision`"),
    ([{"kind": "proposal", "name": "proposal", "revision": "m-12", "position": "delta/0"}],
     "epoch pin without hash pin"),
    ([{"kind": "pack", "name": "f", "position": "p", "ownership": "third_party"}], "third-party"),
    ([{"kind": "pack", "name": "f", "position": "p", "url": "ftp://x"}], "`url`"),
    ([], "array of Source objects"),
])
def test_src_holds_the_source_contract(sources, fragment):
    refused(fragment, l0.read_row, FIXTURE, dict(R01[0], **{"$src": {"memory_need": sources}}))


def test_src_a_cited_manifest_with_its_hash_pin_is_read():
    pinned = {"kind": "proposal", "name": "proposal", "revision": "m-12@d-" + "a" * 64, "position": "delta/0"}
    l0.read_row(FIXTURE, dict(R01[0], **{"$src": {"memory_need": [pinned]}}))


@pytest.mark.parametrize("why, fragment", [
    ({"tags": "rezono:w/1"}, "maps member payloads to proof URIs"),
    ({"tags": {"gpu": "not a uri"}}, "maps member payloads to proof URIs"),
    ({"memory_need": "not a URI"}, "is a proof URI"),
])
def test_why_has_its_shape(why, fragment):
    refused(fragment, l0.read_row, FIXTURE, dict(R01[0], **{"$why": why}))


def test_why_for_a_many_valued_slot_is_read():
    l0.read_row(FIXTURE, dict(R01[0], **{"$why": {"tags": {"gpu": "rezono:w/1"}}}))


def test_a_half_open_valid_needs_its_end():
    case = FILES["V02"]
    row = dict(case["input"][0], **{"$valid": {"at": "2026-01-01..<"}})
    refused("needs an end", l0.read_row, schema_of(case), row)


@pytest.mark.parametrize("change, fragment", [
    ({"kinds": {"Host": {"slots": {"tags": {"derived": "yes"}}}}}, "`derived` is a boolean"),
    ({"kinds": {"Host": {"slots": {"tags": {"min": "garbage"}}}}}, "`min` is not exact"),
    ({"kinds": {"Host": {"iri": []}}}, "`iri` is an absolute IRI"),
    ({"map": {"Host": []}}, "absolute IRI"),
    ({"map": {"Nowhere": "https://schema.org/Thing"}}, "absolute IRI"),
    ({"reasons": {"x": {"label": {"en": []}, "states": ["unknown"]}}}, "maps to text"),
    ({"types": {"Half": {"of": "Integer", "min": "1/2", "max": "9"}}}, "integer text"),
    ({"reasons": {"empty": {"label": {"en": "empty"}, "states": ["unknown"]}}}, "core code `empty` labels only"),
    ({"kinds": {"Host": {"slots": {"tags": {"versions": "garbage"}}}}}, "only a derived slot"),
    ({"kinds": {"Host": {"slots": {"tags": {"derived": True, "versions": [
        {"version": "1", "valid": {"at": "not-a-context"}, "known": "not-a-date"}]}}}}}, "not a"),
])
def test_schema_members_have_their_shape(change, fragment):
    refused(fragment, l0.check_schema, merge(FIXTURE, change))


def test_versions_of_a_derived_slot_are_read():
    ok = merge(FIXTURE, {"kinds": {"Host": {"slots": {"tags": {"derived": True, "versions": [
        {"version": "1", "valid": {"at": "2026-01-01.."}, "known": "2026-01-01"},
        {"version": "2", "valid": {"at": "2027-01-01.."}, "known": "2026-12-01"}]}}}}})
    l0.check_schema(ok)
    bad = copy.deepcopy(ok)
    bad["kinds"]["Host"]["slots"]["tags"]["versions"].reverse()
    refused("version order", l0.check_schema, bad)


def test_a_core_reason_entry_restricts_its_states():
    schema = merge(FIXTURE, {"reasons": {"added_later": {"label": {"en": "added later"}, "states": ["unknown"]}}})
    l0.check_schema(schema)
    refused("may not label `not_applicable`", l0.read_row, schema, dict(R01[1], owner={"$na": "added_later"}))
    l0.read_row(schema, dict(R01[1], owner={"$unknown": "added_later"}))


def test_versioned_axes_name_their_kinds():
    plan = {"world": "closed", "id": {"type": "Text"}, "slots": {}, "versioned": {"during": "missing.Stage"}}
    refused("names no imported kind", l0.check_schema, merge(FIXTURE, {"kinds": {"Plan": plan}}))
    plan = {"world": "closed", "id": {"type": "Text"}, "versioned": {"during": "Host"},
            "applies": {"during": "stage"},
            "slots": {"stage": {"ref": "Team", "card": "1", "states": ["known"]}}}
    refused("reference to the `during` kind", l0.check_schema, merge(FIXTURE, {"kinds": {"Plan": plan}}))


def test_columnar_checks_are_exact():
    refused("differs from the schema's utf8", l0.check_field, FIXTURE, "Host",
            {"name": "tags", "storage": "dictionary<values=int64, indices=int8, ordered=0>"})
    field = copy.deepcopy(FILES["A01"]["input"])
    l0.check_field(schema_of(FILES["A01"]), "Host", field)
    field["extension"]["metadata"]["unexpected"] = None
    refused("`unexpected` differs", l0.check_field, schema_of(FILES["A01"]), "Host", field)
    sid = l0.schema_id(FIXTURE)
    base = {"rezono": "1.0", "schema": sid, "table": "Host", "role": "kind", "dataset": "d-" + "a" * 64}
    refused("manifest id", l0.check_table_metadata, FIXTURE, dict(base, manifest="not-a-manifest"))
    refused("`table_hash`", l0.check_table_metadata, FIXTURE, dict(base, table_hash=None))
    l0.check_table_metadata(FIXTURE, dict(base, manifest="m-12", table_hash="b" * 64))


# A kind tree (§2.1 `parent`): a Server is a Host. It restates Host's slots and adds one of its own; a
# Team points at the hosts it runs, and a server is one of them.
SERVER = {"world": "closed", "id": {"type": "Text"}, "parent": "Host",
          "slots": {**FIXTURE["kinds"]["Host"]["slots"], "rack": {"card": "1", "type": "Text", "states": ["known"]}}}
TREE = merge(FIXTURE, {"kinds": {"Server": SERVER, "Team": {"slots": {
    "runs": {"card": "*", "ref": "Host", "states": ["known"]}}}}})
TREE_ROWS = [
    {"$kind": "Host", "$id": "host-a", "memory_need": "400 GiB", "owner": {"$ref": "ops"}, "tags": ["lab"]},
    {"$kind": "Server", "$id": "srv-1", "memory_need": "64 GiB", "owner": {"$na": ""}, "tags": ["gpu"], "rack": "r1"},
    {"$kind": "Team", "$id": "ops", "runs": [{"$ref": "host-a"}, {"$ref": "srv-1"}]},
]


def test_a_subkind_restates_its_parent_and_its_rows_are_read():
    l0.check_schema(TREE)
    assert l0.read_rows(TREE, TREE_ROWS) == TREE_ROWS
    assert l0.chain(TREE, "Server") == ["Server", "Host"] and l0.root(TREE, "Server") == "Host"
    assert l0.declaring(TREE, "Server", "tags") == "Host" and l0.declaring(TREE, "Server", "rack") == "Server"
    below = merge(TREE, {"kinds": {"Blade": merge(SERVER, {"parent": "Server"})}})  # a tree may be deeper
    l0.check_schema(below)
    assert l0.root(below, "Blade") == "Host"


@pytest.mark.parametrize("patch, fragment", [
    ({"Server": {"parent": "Rack"}}, "`parent` 'Rack' is not a kind of this schema"),
    ({"Host": {"parent": "Server", "slots": {"rack": SERVER["slots"]["rack"]}}}, "`parent` makes a tree"),
    ({"Server": {"slots": {"tags": None}}}, "a subkind restates every slot of its parent `Host`"),
    ({"Server": {"slots": {"owner": {"card": "1"}}}}, "differs from the slot of its parent `Host`"),
    ({"Server": {"id": {"type": "Integer"}}}, "a subkind has the id type of its parent `Host`"),
    ({"Server": {"versioned": {"at": "Date"}}}, "a subkind or its parent is not versioned"),
], ids=["no such kind", "a cycle", "a slot left out", "a slot changed", "another id type", "versioned"])
def test_a_subkind_that_is_not_one_of_its_parent_is_refused(patch, fragment):
    refused(fragment, l0.check_schema, merge(TREE, {"kinds": patch}))


def test_a_restated_slot_states_its_world_against_its_own_kind():
    """`world` on a slot is written where it differs from the kind's, so parent and subkind may spell it apart."""
    l0.check_schema(merge(TREE, {"kinds": {"Host": {"world": "open"}, "Server": {"slots": {"tags": {"world": "open"}}}}}))


def test_a_restated_slot_is_mapped_where_it_is_declared():
    l0.check_schema(merge(TREE, {"map": {"Host.tags": "https://schema.example/keywords"}}))
    refused("map it on the kind that declares it", l0.check_schema,
            merge(TREE, {"map": {"Server.tags": "https://schema.example/keywords"}}))


def test_an_element_of_a_kind_tree_is_written_once():
    """One id names one element in a tree (S1): a row of the subkind and a row of its parent are refused, in
    either order; the same id in another tree is another element."""
    as_host = {k: v for k, v in TREE_ROWS[1].items() if k != "rack"} | {"$kind": "Host"}
    for rows in ([*TREE_ROWS, as_host], [as_host, *TREE_ROWS]):
        refused("is written once, at its most specific kind", l0.read_rows, TREE, rows)
    l0.read_rows(TREE, [*TREE_ROWS, {"$kind": "Team", "$id": "srv-1", "runs": []}])


def test_a_subkind_added_is_minor_and_a_parent_changed_is_major():
    with_server = merge(FIXTURE, {"kinds": {"Server": SERVER}})
    assert l0.classify(FIXTURE, with_server) == ("minor", ["kind `Server` added"])
    assert l0.classify(with_server, merge(with_server, {"kinds": {"Server": {"parent": None}}})) == (
        "major", ["`Server.parent` changed"])
