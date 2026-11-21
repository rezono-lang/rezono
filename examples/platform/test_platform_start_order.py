"""The start order follows from what each service needs, through std-order
(decisions/platform-facts-not-conclusions.md, section 5).

The expected pairs are the needs of the independent reference rows in oracle-rows.json, reversed: a provider
starts before whoever needs it. The step numbers below are those facts/core.yaml held at b77fd2a, kept here to
show that the derived order never runs against them.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parent
# Service.step at b77fd2a: these three had step 2, every other service step 1.
STEP_AT_B77FD2A = {"lab": 2, "restore": 2, "restore-bad": 2}


def _rows():
    from rezono_compiler import scenarios
    from rules_support import states

    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    return model, prog, label, {table: list(values) for table, values in raw.items()}


def _derive(model, prog, label, rows):
    from rules_support import State

    return State(model, prog, label, rows).derived


def _closure(pairs: set) -> set:
    closed = set(pairs)
    while more := {(a, d) for a, b in closed for c, d in closed if b == c} - closed:
        closed |= more
    return closed


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 5. Give std-order an @extend relation "
    "stated_precedes(a, b) that before closes over, with its staged candidate, and re-pin std-order in "
    "packs/std-loop/pack.yaml and examples/platform/pack.yaml and onward; then state stated_precedes(b, a) for each "
    "needs(a, b, _) in examples/platform/rules/core.dl. Keep Service.step and flow_from_step: a planner retires "
    "them. Blocked on planner: adding stated_precedes to std-order breaks protected assertions in "
    "compiler/tests/test_theory_order.py (derived list and reference keys) and "
    "compiler/tests/test_view_theory_axioms.py (reads(order, 'before')), and closing before directly over two "
    "recursive rules hits NotImplementedError in compiler/rezono_compiler/rules_sql.py."))
def test_start_order_follows_from_needs_through_std_order():
    needs = {(a, b) for a, b, _ in json.loads((PLATFORM / "oracle-rows.json").read_text(encoding="utf-8"))["needs"]}
    model, prog, label, rows = _rows()
    assert "stated_precedes" in prog.relations, "std-order has no stated_precedes extension"
    derived = _derive(model, prog, label, rows)
    services = {row[0] for row in rows["service"]}
    stated = {(a, b) for a, b in derived.get("stated_precedes", ()) if a in services or b in services}
    assert stated == {(b, a) for a, b in needs}

    before = derived.get("before", set())
    assert all((a in services) == (b in services) for a, b in before), "before links a service with another element"
    order = {(a, b) for a, b in before if a in services}
    assert order == _closure(stated)
    assert not derived.get("order_cycle"), derived.get("order_cycle")

    # The provider starts first, so in every flow the consumer is the later end, as flow_from_step had it; and the
    # old step numbers never run against the derived order.
    for a, b in sorted(needs):
        assert (b, a) in order and (a, b) not in order, (a, b)
        assert STEP_AT_B77FD2A.get(b, 1) <= STEP_AT_B77FD2A.get(a, 1), (a, b)

    # The step numbers decide nothing, while they are still written.
    if "service__step" in rows:
        changed = dict(rows, service__step=[(service, 1) for service, _ in rows["service__step"]])
        assert {(a, b) for a, b in _derive(model, prog, label, changed)["before"] if a in services} == order
