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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/code-does-not-decide.md, row loop/flow_evidence.py. Add the kinds loop_flow_case (id, run, "
        "source, destination, protocol, port, expected) and loop_flow_witness (id as the evidence reference, run, "
        "case, source, destination, protocol, port, witness, outcome) to packs/std-loop and derive "
        "flow_case_verdict(run, case, state, probe, hubble) with state confirmed or disagreement, and "
        "flow_case_incomplete(run, case). A witness counts only with the case's run and exact tuple; exactly one "
        "probe and one hubble witness are needed. loop/flow_evidence.py then moves to loop/tests as the oracle of "
        "this rule. Today std-loop derives neither relation (AssertionError)."
    ),
)
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
