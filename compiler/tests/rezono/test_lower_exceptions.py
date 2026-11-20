"""Ordered unless blocks lower to rezono.calc/1 definitions with overrides and preserve the exception
precedence, sibling-conflict and unknown-condition semantics of docs/rezono/v0.md section 5b
(decisions/language-exceptions.md, section Lowering).

The lowered definitions are compiled through calc.read and evaluated on both DuckDB and the independent
calculation oracle (calcsupport.run_both).
"""

from pathlib import Path

import pytest

from calcsupport import run_both
from rezono_compiler import calc, pack


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "calc"
PACK = pack.read(FIXTURE)
BINDINGS = {
    "format": "rezono.calc/1",
    "pack": "calc",
    "subject": "item",
    "parameters": "setting.value",
    "inputs": {"kind": "entry", "subject": "item", "fact": "name", "integer": "number", "boolean": "truth"},
}


class MissingExceptionsLowering(AssertionError):
    """rezono_compiler.rezono_exceptions.lower_unless is missing or did not preserve section 5b semantics."""


def lower_leaf(expr: dict) -> dict:
    """Minimal expression lowering for this test's paths and integer literals."""
    if "lit" in expr:
        return {"integer": expr["lit"]}
    if "path" in expr:
        return {"fact": ".".join(expr["path"])}
    raise ValueError(f"unsupported test expression: {expr}")


def scenario_rows() -> dict[str, list[tuple]]:
    """Six subjects covering every rule of docs/rezono/v0.md section 5b:
    - i_base: no exception holds -> base (10)
    - i_pref: first block, first sibling holds -> 20
    - i_override: later block overrides earlier block -> 0
    - i_override_over_unknown: later block holds while earlier block is unknown -> 0
    - i_sibling: two siblings in the same block both hold -> invalid
    - i_unknown: later block condition is missing (unknown) -> unknown, never falls back to earlier block
    """
    entries: list[tuple[str, str, str, bool]] = [
        ("e01", "i_base", "preferred", False),
        ("e02", "i_base", "volume", False),
        ("e03", "i_base", "ineligible", False),
        ("e04", "i_pref", "preferred", True),
        ("e05", "i_pref", "volume", False),
        ("e06", "i_pref", "ineligible", False),
        ("e07", "i_override", "preferred", True),
        ("e08", "i_override", "volume", False),
        ("e09", "i_override", "ineligible", True),
        # i_override_over_unknown omits preferred and volume, but ineligible is known True.
        ("e10", "i_override_over_unknown", "ineligible", True),
        ("e11", "i_sibling", "preferred", True),
        ("e12", "i_sibling", "volume", True),
        ("e13", "i_sibling", "ineligible", False),
        # i_unknown omits ineligible while preferred is True.
        ("e14", "i_unknown", "preferred", True),
        ("e15", "i_unknown", "volume", False),
    ]
    subjects = ["i_base", "i_pref", "i_override", "i_override_over_unknown", "i_sibling", "i_unknown"]
    return {
        "item": [(s,) for s in subjects],
        "entry": [(eid,) for eid, _, _, _ in entries],
        "entry__item": [(eid, subj) for eid, subj, _, _ in entries],
        "entry__name": [(eid, name) for eid, _, name, _ in entries],
        "entry__truth": [(eid, val) for eid, _, _, val in entries],
        "calc__as_of": [("as_of", "2026-03-01", "2026-10-01")],
    }


UNLESS_BLOCKS = [
    [
        {"when": {"path": ["preferred"]}, "then": {"lit": "20"}, "source": "policy#art-1"},
        {"when": {"path": ["volume"]}, "then": {"lit": "15"}, "source": "policy#art-2"},
    ],
    [
        {"when": {"path": ["ineligible"]}, "then": {"lit": "0"}, "source": "policy#art-3"},
    ],
]


@pytest.mark.xfail(
    strict=True,
    raises=MissingExceptionsLowering,
    reason="M3: decisions/language-exceptions.md: Implement compiler/rezono_compiler/rezono_exceptions.py with "
           "lower_unless(rule_id, base_value, unless_blocks, lower_expr) returning rezono.calc/1 definitions "
           "where each block's lines override base and every earlier block (keeping line.get('source') or "
           "'unless' as the override reason) without overriding siblings in the same block.",
)
def test_lower_exceptions():
    try:
        from rezono_compiler import rezono_exceptions
        lower_unless = rezono_exceptions.lower_unless
    except (ImportError, AttributeError) as error:
        raise MissingExceptionsLowering(str(error)) from error

    definitions = lower_unless("discount@v1", {"lit": "10"}, UNLESS_BLOCKS, lower_leaf)
    by_name = {entry["name"]: entry for entry in definitions}
    assert set(by_name) == {"base", "unless_1_1", "unless_1_2", "unless_2_1"}
    assert by_name["unless_1_1"]["overrides"] == [{"definition": "discount@v1#base", "reason": "policy#art-1"}]
    assert by_name["unless_1_2"]["overrides"] == [{"definition": "discount@v1#base", "reason": "policy#art-2"}]
    assert by_name["unless_2_1"]["overrides"] == [
        {"definition": "discount@v1#base", "reason": "policy#art-3"},
        {"definition": "discount@v1#unless_1_1", "reason": "policy#art-3"},
        {"definition": "discount@v1#unless_1_2", "reason": "policy#art-3"},
    ]

    doc = dict(BINDINGS, rules=[{
        "id": "discount@v1",
        "rule": "discount",
        "version": "v1",
        "output": "discount.value",
        "unit": "x",
        "valid_from": "2026-01-01",
        "valid_until": "2027-01-01",
        "known_from": "2025-12-01",
        "definitions": definitions,
    }])
    prog = calc.read(PACK, doc, "calc/discount.yaml")
    duck, oracle = run_both(PACK, prog, doc, scenario_rows())
    assert duck == oracle
    states_and_values = {subject: (row[0], row[1]) for subject, row in duck["discount"].items()}
    assert states_and_values == {
        "i_base": ("known", "10"),
        "i_pref": ("known", "20"),
        "i_override": ("known", "0"),
        "i_override_over_unknown": ("known", "0"),
        "i_sibling": ("invalid", ""),
        "i_unknown": ("unknown", ""),
    }
