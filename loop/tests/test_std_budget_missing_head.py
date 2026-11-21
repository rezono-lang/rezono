"""Missing head observations in packs/std-budget must fail closed, never be treated as 0
(decisions/tooling-does-not-decide.md, Form 1: monotonically shrinking budget).

When a cell has a ceiling or base observation but no head BudgetReading:
- it MUST NOT be granted advisory `budget_slack` (treating absence as 0 hides unmeasured regressions);
- it MUST produce an explicit `budget_missing_head(budget, cell)` finding;
- it MUST NOT hold `budget_within(budget, cell)` (fail closed).

An explicit head BudgetReading of 0 remains valid slack and within budget.
"""

from __future__ import annotations

import pytest

from pack_records import PACKS, evaluate

BUDGET = PACKS / "std-budget"


def test_std_budget_missing_head_observation_fails_closed():
    from rezono_compiler import pack, rules

    assert (BUDGET / "pack.yaml").is_file(), "packs/std-budget does not exist"
    model = pack.read(BUDGET)
    derived = set(rules.load(model.rules).derived())
    required = {
        "budget_raised",
        "budget_exceeded",
        "budget_ratchet_violation",
        "budget_slack",
        "budget_missing_head",
        "budget_within",
    }
    missing_rels = required - derived
    assert not missing_rels, f"packs/std-budget does not derive {sorted(missing_rels)}"

    data = {
        "budget_entry": [
            {"id": "b-steady", "budget": "audit", "cell": "steady", "ceiling": 3, "revision": "base"},
            {"id": "h-steady", "budget": "audit", "cell": "steady", "ceiling": 3, "revision": "head"},
            {"id": "b-zero", "budget": "audit", "cell": "zero-measured", "ceiling": 3, "revision": "base"},
            {"id": "h-zero", "budget": "audit", "cell": "zero-measured", "ceiling": 3, "revision": "head"},
            {"id": "b-miss-base", "budget": "audit", "cell": "missing-head-with-base", "ceiling": 4, "revision": "base"},
            {"id": "h-miss-base", "budget": "audit", "cell": "missing-head-with-base", "ceiling": 4, "revision": "head"},
            {"id": "b-miss-ceil", "budget": "audit", "cell": "missing-head-ceiling-only", "ceiling": 2, "revision": "base"},
            {"id": "h-miss-ceil", "budget": "audit", "cell": "missing-head-ceiling-only", "ceiling": 2, "revision": "head"},
            {"id": "b-miss-zero", "budget": "audit", "cell": "missing-head-zero-ceiling", "ceiling": 0, "revision": "base"},
            {"id": "h-miss-zero", "budget": "audit", "cell": "missing-head-zero-ceiling", "ceiling": 0, "revision": "head"},
            {"id": "b-over", "budget": "audit", "cell": "exceeded", "ceiling": 2, "revision": "base"},
            {"id": "h-over", "budget": "audit", "cell": "exceeded", "ceiling": 2, "revision": "head"},
            {"id": "b-raised", "budget": "audit", "cell": "raised", "ceiling": 2, "revision": "base"},
            {"id": "h-raised", "budget": "audit", "cell": "raised", "ceiling": 3, "revision": "head"},
            {"id": "b-ratchet", "budget": "audit", "cell": "ratchet", "ceiling": 5, "revision": "base"},
            {"id": "h-ratchet", "budget": "audit", "cell": "ratchet", "ceiling": 5, "revision": "head"},
        ],
        "budget_reading": [
            {"id": "rb-steady", "budget": "audit", "cell": "steady", "observed": 3, "revision": "base"},
            {"id": "rh-steady", "budget": "audit", "cell": "steady", "observed": 3, "revision": "head"},
            {"id": "rb-zero", "budget": "audit", "cell": "zero-measured", "observed": 3, "revision": "base"},
            {"id": "rh-zero", "budget": "audit", "cell": "zero-measured", "observed": 0, "revision": "head"},
            {"id": "rb-miss-base", "budget": "audit", "cell": "missing-head-with-base", "observed": 4, "revision": "base"},
            {"id": "rb-miss-obs", "budget": "audit", "cell": "missing-head-base-obs-only", "observed": 2, "revision": "base"},
            {"id": "rb-over", "budget": "audit", "cell": "exceeded", "observed": 2, "revision": "base"},
            {"id": "rh-over", "budget": "audit", "cell": "exceeded", "observed": 3, "revision": "head"},
            {"id": "rb-raised", "budget": "audit", "cell": "raised", "observed": 2, "revision": "base"},
            {"id": "rh-raised", "budget": "audit", "cell": "raised", "observed": 2, "revision": "head"},
            {"id": "rb-ratchet", "budget": "audit", "cell": "ratchet", "observed": 2, "revision": "base"},
            {"id": "rh-ratchet", "budget": "audit", "cell": "ratchet", "observed": 3, "revision": "head"},
        ],
    }

    _, rows, _ = evaluate(model, data)

    expected_missing = {
        ("audit", "missing-head-with-base"),
        ("audit", "missing-head-ceiling-only"),
        ("audit", "missing-head-base-obs-only"),
        ("audit", "missing-head-zero-ceiling"),
    }
    assert rows["budget_missing_head"] == expected_missing
    assert rows["budget_slack"] == {
        ("audit", "zero-measured"),
        ("audit", "ratchet"),
    }, f"missing head readings must never be treated as 0 / granted slack: {rows['budget_slack']}"
    assert rows["budget_within"] == {
        ("audit", "steady"),
        ("audit", "zero-measured"),
    }, f"cells with missing head readings or violations must not hold budget_within: {rows['budget_within']}"
    assert rows["budget_raised"] == {("audit", "raised")}
    assert rows["budget_exceeded"] == {("audit", "exceeded")}
    assert rows["budget_ratchet_violation"] == {("audit", "exceeded"), ("audit", "ratchet")}
