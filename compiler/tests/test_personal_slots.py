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
        pos_codes = [d.code for d in getattr(pos_err, "diagnostics", ())]
        assert "R054" in pos_codes or "R054" in str(pos_err), (
            f"expected R054 diagnostic when a rule reads personal slot alpha.secret_note, got: {pos_err}"
        )
        assert "secret_note" in str(pos_err), pos_err
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
        agg_codes = [d.code for d in getattr(agg_err, "diagnostics", ())]
        assert "R054" in agg_codes or "R054" in str(agg_err), (
            f"expected R054 diagnostic when an aggregate reads personal slot alpha.secret_note, got: {agg_err}"
        )
        assert "secret_note" in str(agg_err), agg_err
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


def _refused_codes(directory: Path) -> list[str]:
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
    assert _refused_codes(directory) == ["R054"]


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
    assert _refused_codes(directory) == ["R054"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: R054 refuses a rule that reads any table belonging to a "
        "personal attribute, the parameter table of its bound included (section 3), as the checker does. Waits "
        "for compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which "
        "lifts it with the fix."
    ),
)
def test_rule_reading_a_parameter_table_of_a_personal_slot_is_refused(tmp_path: Path):
    rule = ".decl capped(v: number)\ncapped(v) :- alpha__secret_count__maximum(v).\n"

    def made(name: str, personal: bool) -> Path:
        directory = _personal_pack(tmp_path / name, rule)
        schema_path = directory / "schema" / "minimal.yaml"
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        schema["classes"]["Alpha"]["attributes"]["secret_count"] = {
            "range": "integer", "maximum_value": 9, **({"annotations": {"personal": True}} if personal else {})}
        schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")
        return directory

    emit.compile_pack(pack.read(made("plain", False)))  # counter-case: the bound of a slot that is not personal
    assert _refused_codes(made("personal", True)) == ["R054"]
