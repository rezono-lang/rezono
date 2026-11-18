"""Management loss blocks changes without stopping consumers of the affected clusters."""
import pytest

from case_support import ROOT, verified
from rezono_compiler import calc, facts, pack, rules
from rules_support import State


class MissingPlatformRule(Exception):
    pass


def evaluate(model, program, records):
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    return State(model, program, "platform-case", facts.rows_of(model, records), calculation)

NEEDS = (
    ("west-control", "manager", "change"), ("east-control", "manager", "change"),
    ("west-api", "west-control", "run"), ("east-api", "east-control", "run"),
    ("manager", "directory", "run"), ("directory", "disk", "run"),
    ("status", "directory", "change"), ("monitor", "status", "run"),
)


def impacts(cause, needs):
    # Independent breadth-first expansion. Only complete outages enter the next frontier.
    down, frontier, locked = {cause}, {cause}, set()
    while frontier:
        locked.update(a for a, b, mode in needs if mode == "change" and b in frontier)
        frontier = {a for a, b, mode in needs if mode == "run" and b in frontier} - down
        down.update(frontier)
    return {(a, "down") for a in down - {cause}} | {(a, "change_blocked") for a in locked - down}


def test_management_and_runtime_frontiers():
    assert impacts("manager", NEEDS) == {("west-control", "change_blocked"), ("east-control", "change_blocked")}
    assert impacts("disk", NEEDS) == {("directory", "down"), ("manager", "down"), ("status", "change_blocked"),
                                      ("west-control", "change_blocked"), ("east-control", "change_blocked")}
    assert impacts("monitor", NEEDS) == set()


@pytest.mark.xfail(strict=True, raises=MissingPlatformRule,
                   reason="Implement typed run/change needs and recursive outage_impact in examples/platform/schema and rules. Read decisions/platform-outage-chain.md.")
def test_recursive_outages_and_checked_need_chains():
    model = pack.read(ROOT)
    program = rules.load(model.rules)
    relation = "outage_impact"
    if relation not in program.derived():
        raise MissingPlatformRule(relation)
    assert any(program.recursive(r) and program.reaches(r, relation) for r in program.derived())
    changed = tuple((a, b, "run" if a == "west-control" else mode) for a, b, mode in NEEDS)
    for needs in (NEEDS, changed):
        links = [dict(id=f"link-{i}", consumer=a, provider=b, mode=mode) for i, (a, b, mode) in enumerate(needs)]
        for cause in ("manager", "disk", "monitor"):
            state = evaluate(model, program, {"service_need": links, "failure_observation": [{"id": cause}]})
            want = {(cause, a, effect) for a, effect in impacts(cause, needs)}
            assert state.derived[relation] == want
            for key in want:
                leaves = verified(relation, key, state=(model, state))
                assert ("failure_observation", (cause,)) in leaves
                # The fixture has one path per affected service. Verify every authored hop, including its mode.
                node = key[1]
                while node != cause:
                    edge, = [link for link in links if link["consumer"] == node]
                    for slot in ("consumer", "provider", "mode"):
                        assert (f"service_need__{slot}", (edge["id"], edge[slot])) in leaves
                    node = edge["provider"]
