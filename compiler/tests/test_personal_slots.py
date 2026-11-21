"""Personal slots and compiler refusal `R054` (decisions/personal-data-handling.md).

A slot marked `personal` may not be read by any rule (positive literal, negative literal, or aggregate).
The compiler refuses any rule reading a personal slot with diagnostic `R054`, while a pack whose rules read
only non-personal slots compiles cleanly and marks `personal: true` on the attribute in `schema-bundle.json`.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, pack, rules_dl

ROOT = Path(__file__).resolve().parents[2]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"


def _personal_pack(directory: Path, rule_text: str) -> Path:
    shutil.copytree(MINIMAL, directory)
    schema_path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["classes"]["Alpha"]["attributes"]["secret_note"] = {
        "range": "string",
        "annotations": {"personal": True},
    }
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")

    labels_path = directory / "labels" / "nl.yaml"
    labels_path.write_text(
        labels_path.read_text(encoding="utf-8") + "alpha.secret_note: vertrouwelijke aantekening\n",
        encoding="utf-8",
        newline="\n",
    )

    (directory / "rules").mkdir()
    (directory / "rules" / "derive.dl").write_text(rule_text, encoding="utf-8", newline="\n")
    return directory


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: Support the `personal` slot annotation in "
        "compiler/rezono_compiler/pack.py, rezono_slot.py, rezono/src/module-slot.ts, and contracts/bundle.yaml; "
        "refuse any rule or calculation reading a `personal` slot with diagnostic `R054` (in rules_dl.py, "
        "native_rule_signatures.py, rezono/src/native-rule-check.ts, and checker)."
    ),
)
def test_rule_reading_personal_slot_is_refused(tmp_path: Path):
    # 1. Positive body literal reading a personal slot must be refused with R054.
    positive_dir = _personal_pack(
        tmp_path / "positive",
        ".decl exposed(x: symbol, v: symbol)\n"
        "exposed(x, v) :- alpha__secret_note(x, v).\n",
    )
    try:
        emit.compile_pack(pack.read(positive_dir))
    except (pack.CompileError, rules_dl.RuleError) as pos_err:
        # R054's sentence names the slot, but a diagnostic has no argument for it (contracts/diagnostic.yaml) and a
        # test compares no sentence: so the code and the place of the reading atom.
        assert [(d.code, d.where) for d in pos_err.diagnostics] == [("R054", "rules/derive.dl:2")], pos_err
    else:
        raise AssertionError("rule reading personal slot alpha__secret_note must be refused with R054")

    # 2. Aggregate reading a personal slot must also be refused with R054.
    agg_dir = _personal_pack(
        tmp_path / "aggregate",
        ".decl counted(x: symbol, n: number)\n"
        "counted(x, n) :- alpha(x), n = count : { alpha__secret_note(x, _) }.\n",
    )
    try:
        emit.compile_pack(pack.read(agg_dir))
    except (pack.CompileError, rules_dl.RuleError) as agg_err:
        assert [(d.code, d.where) for d in agg_err.diagnostics] == [("R054", "rules/derive.dl:2")], agg_err
    else:
        raise AssertionError("aggregate reading personal slot alpha__secret_note must be refused with R054")

    # 3. Counter-case: a rule reading only a non-personal slot compiles cleanly and marks personal: true in bundle.
    ok_dir = _personal_pack(
        tmp_path / "allowed",
        ".decl titled(x: symbol, v: symbol)\n"
        "titled(x, v) :- alpha__title(x, v).\n",
    )
    model = pack.read(ok_dir)
    assert getattr(model.kinds["alpha"].slots["secret_note"], "personal", False) is True
    assert getattr(model.kinds["alpha"].slots["title"], "personal", False) is False

    compiled = emit.compile_pack(model)
    bundle = json.loads(compiled["bundle/schema-bundle.json"])
    attrs = {a["id"]: a for a in bundle["attributes"]}
    assert attrs["alpha.secret_note"].get("personal") is True
    assert "personal" not in attrs["alpha.title"]


def refused_codes(directory: Path) -> list[str]:
    """The diagnostic codes compiling `directory` is refused with; an AssertionError when it compiles."""
    try:
        emit.compile_pack(pack.read(directory))
    except (pack.CompileError, rules_dl.RuleError) as refused:
        return [d.code for d in refused.diagnostics]
    raise AssertionError(f"{directory.name}: compiled, but reads a personal slot")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A path equation that runs over a personal slot reads it, so "
        "the compiler refuses it with R054, its one refusal for reading a personal slot. Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("left, right", [
    ("alpha.secret_note", "alpha"),
    ("alpha", "alpha.secret_note"),
], ids=["left", "right"])
def test_path_equation_over_a_personal_slot_is_refused(tmp_path: Path, left: str, right: str):
    """decisions/personal-data-handling.md, section 2: a personal slot may not participate in a path_equation."""
    directory = _personal_pack(tmp_path / "pack",
                               ".decl titled(x: symbol, v: symbol)\ntitled(x, v) :- alpha__title(x, v).\n")
    schema_path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))

    def equation(left: str, right: str) -> None:
        schema["classes"]["Beta"]["annotations"] = {"path_equations": [{"name": "same", "left": left, "right": right}]}
        schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")

    equation("alpha", "alpha")  # counter-case: the same pack with an equation over arrows only compiles
    emit.compile_pack(pack.read(directory))
    equation(left, right)
    assert refused_codes(directory) == ["R054"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: R054 refuses a rule that reads a personal slot in a negative "
        "body literal (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_negated_literal_reading_a_personal_slot_is_refused(tmp_path: Path):
    directory = _personal_pack(tmp_path / "pack",
                               ".decl hidden(x: symbol)\nhidden(x) :- alpha(x), !alpha__secret_note(x, \"x\").\n")
    assert refused_codes(directory) == ["R054"]


def test_rule_reading_a_parameter_table_of_a_personal_slot_compiles(tmp_path: Path):
    """A bound of a personal slot is the same for everyone, so it is not personal (the owner, 21-11)."""
    rule = ".decl capped(v: number)\ncapped(v) :- alpha__secret_count__maximum(v).\n"
    directory = _personal_pack(tmp_path / "pack", rule)
    schema_path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["classes"]["Alpha"]["attributes"]["secret_count"] = {
        "range": "integer", "maximum_value": 9, "annotations": {"personal": True}}
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")
    emit.compile_pack(pack.read(directory))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: R054 refuses a rule that reads the state table of a personal "
        "slot, as it refuses its own table (section 3, the owner, 21-11). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_rule_reading_the_state_table_of_a_personal_slot_is_refused(tmp_path: Path):
    rule = ".decl seen(x: symbol)\nseen(x) :- alpha__secret_note_state(x, s, r).\n"
    assert refused_codes(_personal_pack(tmp_path / "pack", rule)) == ["R054"]


# A rule over Beta only, so that sealing Alpha leaves it valid.
STATED = ".decl stated(x: symbol, v: symbol)\nstated(x, v) :- beta__state(x, v).\n"
RDFS = {"linkml": "https://w3id.org/linkml/", "rdfs": "http://www.w3.org/2000/01/rdf-schema#"}


def _with_schema(directory: Path, change) -> Path:
    path = directory / "schema" / "minimal.yaml"
    schema = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(schema)
    path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")
    return directory


def _not_personal(schema: dict) -> None:
    """The same schema with no slot marked personal: the counter-case."""
    for cls in schema["classes"].values():
        for slot in (cls.get("attributes") or {}).values():
            (slot.get("annotations") or {}).pop("personal", None)


def _explored(s: dict) -> None:
    s["classes"]["Alpha"]["attributes"]["secret_count"] = {
        "range": "integer", "minimum_value": 0, "maximum_value": 9,
        "annotations": {"personal": True, "explore": {"value": {"step": 1}}}}


def _constant(s: dict) -> None:
    s["classes"]["Alpha"]["attributes"]["secret_note"]["equals_string"] = "x"


def _named(s: dict) -> None:
    s["prefixes"] = RDFS
    s["classes"]["Alpha"]["attributes"]["secret_note"]["slot_uri"] = "rdfs:label"


def _unique_key(s: dict) -> None:
    s["classes"]["Alpha"]["unique_keys"] = {"by_note": {"unique_key_slots": ["secret_note"]}}


def _sealed(s: dict, period: dict) -> None:
    """Alpha sealed on `period`, with PeriodClose and its cover kind ClosedAlpha (as compiler/tests/test_seal.py)."""
    s["classes"]["Alpha"]["attributes"]["period"] = period
    s["classes"]["Alpha"]["annotations"] = {"seal": "period"}
    s["classes"]["PeriodClose"] = {"attributes": {
        "id": {"identifier": True}, "closed_until": {"range": "date", "required": True},
        "covers": {"range": "ClosedAlpha", "multivalued": True, "inlined_as_list": True}}}
    s["classes"]["ClosedAlpha"] = {"attributes": {"element": {"range": "Alpha", "required": True},
                                                  "sha256": {"required": True}}}


def _sealed_on_personal_period(s: dict) -> None:
    s["classes"]["Alpha"]["attributes"]["secret_note"]["annotations"].pop("personal")
    _sealed(s, {"range": "date", "required": True, "annotations": {"personal": True}})


def _sealed_beside_personal_slot(s: dict) -> None:
    _sealed(s, {"range": "date", "required": True})


@pytest.mark.parametrize("change", [
    pytest.param(
        lambda s: s["annotations"].update(personal=True), id="schema",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: `personal` goes only on a scalar attribute, as a "
            "boolean (section 2): `personal` on a schema is refused with invalid_personal_annotation. Waits "
            "for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), "
            "which lifts it with the fix."
        )),
    ),
    pytest.param(
        lambda s: s["classes"]["Alpha"].update(annotations={"personal": True}), id="class",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: `personal` goes only on a scalar attribute, as a "
            "boolean (section 2): `personal` on a class is refused with invalid_personal_annotation. Waits "
            "for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), "
            "which lifts it with the fix."
        )),
    ),
    pytest.param(
        lambda s: s["classes"]["Alpha"]["attributes"]["id"].update(annotations={"personal": True}), id="identifier",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: `personal` goes only on a scalar attribute, as a "
            "boolean (section 2): `personal` on an identifier is refused with invalid_personal_annotation. "
            "Waits for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused "
            "(#1342), which lifts it with the fix."
        )),
    ),
    pytest.param(
        lambda s: s["classes"]["Beta"]["attributes"]["alpha"].update(annotations={"personal": True}), id="arrow",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: `personal` goes only on a scalar attribute, as a "
            "boolean (section 2): `personal` on an arrow is refused with invalid_personal_annotation. Waits "
            "for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), "
            "which lifts it with the fix."
        )),
    ),
    pytest.param(
        lambda s: s["classes"]["Alpha"]["attributes"]["secret_note"]["annotations"].update(personal="yes"),
        id="not-boolean",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: `personal` goes only on a scalar attribute, as a "
            "boolean (section 2): a `personal` value that is not a boolean is refused with "
            "invalid_personal_annotation. Waits for "
            "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
            "lifts it with the fix."
        )),
    ),
])
def test_personal_annotation_out_of_place_is_refused(tmp_path: Path, change):
    """decisions/personal-data-handling.md, section 2: `personal` is a boolean on a scalar attribute."""
    directory = _with_schema(_personal_pack(tmp_path / "pack", STATED), change)
    assert refused_codes(directory) == ["invalid_personal_annotation"]


@pytest.mark.parametrize("change", [
    pytest.param(
        _explored, id="explore",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in a sweep "
            "(explore) (section 2): the compiler refuses it with personal_slot_disallowed. Waits for "
            "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
            "lifts it with the fix."
        )),
    ),
    pytest.param(
        _constant, id="constant",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in a public "
            "constant (section 2): the compiler refuses it with personal_slot_disallowed. Waits for "
            "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
            "lifts it with the fix."
        )),
    ),
    pytest.param(
        _named, id="name",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in the "
            "rdfs:label name of a kind (section 2): the compiler refuses it with personal_slot_disallowed. "
            "Waits for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused "
            "(#1342), which lifts it with the fix."
        )),
    ),
    pytest.param(
        _unique_key, id="unique-key",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in a unique_key "
            "(section 2): the compiler refuses it with personal_slot_disallowed. Waits for "
            "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
            "lifts it with the fix."
        )),
    ),
    pytest.param(
        _sealed_on_personal_period, id="seal-period",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in a seal as its "
            "period (section 2): the compiler refuses it with personal_slot_disallowed. Waits for "
            "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
            "lifts it with the fix."
        )),
    ),
    pytest.param(
        _sealed_beside_personal_slot, id="seal-family",
        marks=pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
            "extra: decisions/personal-data-handling.md: A personal slot may not participate in a seal as a "
            "slot of the sealed kind (section 2): the compiler refuses it with personal_slot_disallowed. "
            "Waits for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused "
            "(#1342), which lifts it with the fix."
        )),
    ),
])
def test_personal_slot_cannot_take_part_in_a_schema_construct(tmp_path: Path, change):
    """decisions/personal-data-handling.md, section 2: a personal slot may not participate in a unique_key, a sweep, a
    seal, or a public constant or rdfs:label. The same schema with no slot marked personal compiles."""
    plain = _with_schema(_personal_pack(tmp_path / "plain", STATED), lambda s: (change(s), _not_personal(s)))
    emit.compile_pack(pack.read(plain))
    directory = _with_schema(_personal_pack(tmp_path / "pack", STATED), change)
    assert refused_codes(directory) == ["personal_slot_disallowed"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A class rule condition reads its slot, so a condition on a "
        "personal slot is refused with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_class_rule_condition_on_a_personal_slot_is_refused(tmp_path: Path):
    def ruled(slot: str):
        return lambda s: s["classes"]["Alpha"].update(rules=[{
            "preconditions": {"slot_conditions": {slot: {"equals_string": "x"}}},
            "postconditions": {"slot_conditions": {"size": {"required": True}}}}])

    emit.compile_pack(pack.read(_with_schema(_personal_pack(tmp_path / "plain", STATED), ruled("title"))))
    assert refused_codes(_with_schema(_personal_pack(tmp_path / "pack", STATED), ruled("secret_note"))) == ["R054"]
