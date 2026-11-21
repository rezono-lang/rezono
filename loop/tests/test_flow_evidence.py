"""Require independent run-scoped probe and Hubble observations."""

from flow_evidence import assess


def test_flow_evidence():
    case = {"run": "r", "id": "echo-ok", "source": "sender", "destination": "echo", "port": 8080,
            "protocol": "TCP", "expected": "allow"}
    probe = {**case, "witness": "probe", "outcome": "allow", "ref": "p"}
    hubble = {**case, "witness": "hubble", "outcome": "allow", "ref": "h"}
    assert assess(case, [probe, hubble]) == ("confirmed", ("p", "h"))
    assert assess(case, [probe, {**hubble, "outcome": "deny"}]) == ("disagreement", ("p", "h"))
    assert assess(case, [probe, {**hubble, "run": "old"}])[0] == "incomplete"
