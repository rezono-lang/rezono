"""Calculations and personal slots (decisions/personal-data-handling.md, section 3).

No calculation may read a `personal` slot: not as its parameters, not through its parameter_choice, not
through the slots its inputs are bound to, and not in a fact leaf. The compiler refuses each with `R054`,
while the same calculation over slots that are not personal compiles.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import emit, pack, rules_dl

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "calc"
CHOICE = {"name": "name", "valid_from": "valid_from", "valid_until": "valid_until", "known_from": "known_from"}
INPUTS = {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"}


def _calculation(value: dict, when: dict | None = None, **bindings) -> dict:
    """A calculation over `item` with one rule of one definition."""
    rule = {"id": "total@v1", "rule": "total", "version": "v1", "output": "total.value", "unit": "x",
            "valid_from": "2026-01-01", "valid_until": "2027-01-01", "known_from": "2025-12-01",
            "definitions": [{"name": "base", "when": when or {"boolean": True}, "value": value}]}
    return {"format": "rezono.calc/1", "pack": "calc", "subject": "item", **bindings, "rules": [rule]}


def _calc_pack(directory: Path, calculation: dict, personal: str | None = None) -> Path:
    """The calc fixture with `calculation` as its calc file; `personal` (`Class.attribute`) is marked personal."""
    shutil.copytree(FIXTURE, directory)
    if personal is not None:
        schema_path = directory / "schema" / "calc.yaml"
        schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
        cls, _, attribute = personal.partition(".")
        schema["classes"][cls]["attributes"][attribute]["annotations"] = {"personal": True}
        schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8", newline="\n")
    (directory / "calc" / "example.yaml").write_text(yaml.safe_dump(calculation, sort_keys=False),
                                                     encoding="utf-8", newline="\n")
    return directory


def _compiles(directory: Path) -> None:
    """Counter-case: the pack with its calculation compiles."""
    emit.compile_pack(pack.read(directory))


def _refused_codes(directory: Path) -> list[str]:
    """The diagnostic codes compiling `directory` is refused with; an AssertionError when it compiles."""
    try:
        emit.compile_pack(pack.read(directory))
    except (pack.CompileError, rules_dl.RuleError) as refused:
        return [d.code for d in getattr(refused, "diagnostics", ())]
    else:
        raise AssertionError(f"{directory.name}: compiled, but its calculation reads a personal slot")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A calculation whose parameters are a personal attribute "
        "reads that attribute, so the compiler refuses it with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
def test_parameters_bound_to_a_personal_slot_are_refused(tmp_path: Path):
    calculation = _calculation({"parameter": "s0"}, parameters="setting.value")
    _compiles(_calc_pack(tmp_path / "plain", calculation))
    assert _refused_codes(_calc_pack(tmp_path / "personal", calculation, personal="Setting.value")) == ["R054"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A parameter_choice that binds a personal slot reads it to "
        "choose the parameters, so the compiler refuses it with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("role", sorted(CHOICE))
def test_a_parameter_choice_over_a_personal_slot_is_refused(tmp_path: Path, role: str):
    calculation = _calculation({"parameter": "rate"}, parameters="setting.value", parameter_choice=CHOICE)
    _compiles(_calc_pack(tmp_path / "plain", calculation))
    personal = f"Setting.{CHOICE[role]}"
    assert _refused_codes(_calc_pack(tmp_path / "personal", calculation, personal=personal)) == ["R054"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: Calculation inputs bound to a personal slot read it, so "
        "the compiler refuses them with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("role", ["fact", "integer", "boolean"])
def test_inputs_bound_to_a_personal_slot_are_refused(tmp_path: Path, role: str):
    calculation = _calculation({"op": "add", "args": [{"fact": "x0"}, {"integer": "1"}]}, inputs=INPUTS)
    _compiles(_calc_pack(tmp_path / "plain", calculation))
    personal = f"Entry.{INPUTS[role]}"
    assert _refused_codes(_calc_pack(tmp_path / "personal", calculation, personal=personal)) == ["R054"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/personal-data-handling.md: A fact leaf of a calculation that names a personal "
        "attribute reads it, so the compiler refuses it with R054 (section 3). Waits for "
        "compiler/tests/test_personal_slots.py--test_rule_reading_personal_slot_is_refused (#1342), which lifts "
        "it with the fix."
    ),
)
@pytest.mark.parametrize("place, attribute", [("value", "amount"), ("when", "flag")])
def test_a_fact_leaf_reading_a_personal_slot_is_refused(tmp_path: Path, place: str, attribute: str):
    leaf = {"fact": f"item.{attribute}"}
    calculation = _calculation(leaf, None) if place == "value" else _calculation({"integer": "1"}, leaf)
    _compiles(_calc_pack(tmp_path / "plain", calculation))
    personal = f"Item.{attribute}"
    assert _refused_codes(_calc_pack(tmp_path / "personal", calculation, personal=personal)) == ["R054"]
