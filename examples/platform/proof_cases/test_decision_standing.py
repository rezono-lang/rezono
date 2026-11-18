"""Date-based standings and review findings over decisions with identical recorded states."""
import pytest

from case_support import ROOT, verified
from rezono_compiler import calc, facts, pack, rules
from rules_support import State


class MissingPlatformRule(Exception):
    pass


def evaluate(model, program, records):
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    return State(model, program, "platform-case", facts.rows_of(model, records), calculation)

from case_support import imported


def decision(key, start=1, end=None, replaces=None):
    record = dict(id=key, title=key, state="in_force", decider=["board"],
                  valid_from=f"2026-04-{start:02}", valid_from_day=20260400 + start)
    if end is not None:
        record.update(valid_until=f"2026-04-{end:02}", valid_until_day=20260400 + end)
    if replaces:
        record["supersedes"] = [replaces]
    return record


def decisions(replace=True):
    records = [decision("earlier"), decision("withdrawal", 8, replaces="earlier" if replace else None),
               decision("timeboxed", end=8), decision("position"), decision("other-position"),
               decision("exclusion", 8, 10), decision("review-old"), decision("review-new", 8, replaces="review-old")]
    records.extend(decision(k) for k in ("matrix", "stance", "capacity", "cost"))
    return {"decision": records, "reference_date": [
        {"id": d, "title": d, "day": 20260400 + n} for d, n in [("before", 7), ("edge", 8), ("after", 10)]],
        "ground": [{"id":"dep-1", "decision": "position", "rests_on":"earlier"},
                   {"id":"dep-2", "decision":"other-position", "rests_on":"timeboxed"}]}


def test_standard_decision_distinguishes_expiry_from_withdrawal():
    theory = pack.read(ROOT.parents[1] / "packs" / "std-decision")
    state = evaluate(theory, rules.load(theory.rules), decisions())
    assert ("timeboxed", "edge") in state.derived["ended"]
    assert ("earlier", "withdrawal", "edge") in state.derived["replaced"]
    assert not any(row[0] == "timeboxed" for row in state.derived["replaced"])
    assert ("position", "edge") in state.derived["in_force_on"]
    assert not {("timeboxed","edge"),("earlier","edge"),("exclusion","after")} & state.derived["in_force_on"]


@pytest.mark.xfail(strict=True, raises=MissingPlatformRule,
                   reason="Import std-decision and add dated grounds, placement and exclusion findings to examples/platform/schema and rules. Read decisions/platform-decision-standing.md.")
def test_platform_recalculates_and_retains_conflicting_placements():
    model = pack.read(ROOT)
    program = rules.load(model.rules)
    outputs = ("effective_platform_decision", "review_required", "placement_exclusion")
    if not set(outputs) <= set(program.derived()):
        raise MissingPlatformRule(", ".join(outputs))
    imported("std-decision")
    assert program.reaches("replaced", "review_required")
    for rel in outputs:
        assert program.reaches("in_force_on", rel)
        # Outside the standard predicates, even an extra independent shortcut to recorded status is forbidden.
        pending, visited = [rel], set()
        while pending:
            name = pending.pop()
            if name in visited or name in {"in_force_on", "replaced", "ended"}:
                continue
            visited.add(name)
            assert name != "decision__state"
            pending.extend(program.deps(name) if name in program.derived() else ())
    bindings = [("review-old","review","outbound","allow"),("review-new","review","outbound","deny"),
                ("position","placement","fern","ridge"),("other-position","placement","reed","lake"),
                ("exclusion","exclusion","fern","ridge"),("matrix","zone_matrix","tenant-egress","review"),
                ("stance","product_stance","ink","active"),("capacity","capacity","ridge","13"),
                ("cost","shared_cost","april","109")]
    for replace in (True, False):
        records = decisions(replace)
        records["platform_decision_binding"] = [dict(id=k, decision=k, area=a, subject=t, value=v)
                                                for k, a, t, v in bindings]
        state = evaluate(model, program, records)
        dates = ("before","edge","after")
        expected = {(k,a,t,v,d) for k,a,t,v in bindings for d in dates
                    if not ((k == "review-new" and d == "before") or (k == "review-old" and d != "before")
                            or (k == "exclusion" and d != "edge"))}
        assert state.derived[outputs[0]] == expected
        assert state.derived[outputs[1]] == ({("position","earlier","withdrawal",d) for d in dates[1:]} if replace else set())
        conflict = ("position", "exclusion", "fern","ridge","edge")
        assert state.derived[outputs[2]] == {conflict}
        proof = state.proof(outputs[2], conflict)
        positive = {(p["row"]["relation"], p["row"]["key"]) for w in proof["witnesses"] for p in w["premises"]
                    if p["polarity"] == "positive"}
        import json
        assert {("in_force_on", (k,"edge")) for k in ("position","exclusion")} <= {
            (rel,tuple(json.loads(key))) for rel,key in positive}
        verified(outputs[2], conflict, state=(model,state))
        if replace:
            leaves = verified(outputs[1], ("position","earlier","withdrawal","edge"), state=(model,state))
            assert {("decision__supersedes",("withdrawal","earlier")),("ground__rests_on",("dep-1","earlier")),
                    ("ground__decision",("dep-1","position"))} <= leaves
