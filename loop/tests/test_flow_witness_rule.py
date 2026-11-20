"""A flow case is confirmed by two independent witnesses in std-loop rules: decisions/code-does-not-decide.md.

The expectation is the behaviour of loop/flow_evidence.py and decisions/loop-design.md, "Verify network policy in
the disposable cluster": a rule reports disagreement between the expected decision and either witness, and
missing or ambiguous evidence is incomplete.
"""
import pytest

from pack_records import LOOP, evaluate

CASE = {"id": "echo-ok", "run": "r", "source": "sender", "destination": "echo", "protocol": "TCP", "port": 8080,
        "expected": "allow"}


def witness(ref, kind, outcome, **overrides):
    scope = {key: CASE[key] for key in ("run", "source", "destination", "protocol", "port")}
    return {"id": ref, **scope, "case": CASE["id"], "witness": kind, "outcome": outcome, **overrides}


def judge(cases, witnesses):
    from rezono_compiler import pack, rules

    model = pack.read(LOOP)
    missing = {"flow_case_verdict", "flow_case_incomplete"} - set(rules.load(model.rules).derived())
    assert not missing, f"std-loop does not derive {sorted(missing)}"
    _, rows, _ = evaluate(model, {"loop_flow_case": cases, "loop_flow_witness": witnesses})
    return rows["flow_case_verdict"], rows["flow_case_incomplete"]


def test_flow_witnesses_are_judged_by_the_loop_pack():
    probe, hubble = witness("p", "probe", "allow"), witness("h", "hubble", "allow")
    assert judge([CASE], [probe, hubble]) == ({("r", "echo-ok", "confirmed", "p", "h")}, set())
    denied = witness("h", "hubble", "deny")
    assert judge([CASE], [probe, denied]) == ({("r", "echo-ok", "disagreement", "p", "h")}, set())
    old = witness("h", "hubble", "allow", run="old")
    assert judge([CASE], [probe, old]) == (set(), {("r", "echo-ok")})
    second = witness("p2", "probe", "allow")
    assert judge([CASE], [probe, second, hubble]) == (set(), {("r", "echo-ok")})
    closed = {**CASE, "expected": "deny"}
    refused = [witness("p", "probe", "deny"), witness("h", "hubble", "deny")]
    assert judge([closed], refused) == ({("r", "echo-ok", "confirmed", "p", "h")}, set())
