"""Require independent run-scoped probe and Hubble observations."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/flow_evidence.py. Require independent run-scoped probe and Hubble observations.")
def test_flow_evidence():
    assess = run_path(str(Path(__file__).resolve().parents[1] / "flow_evidence.py"))["assess"]
    case = {"run": "r", "id": "echo-ok", "source": "sender", "destination": "echo", "port": 8080,
            "protocol": "TCP", "expected": "allow"}
    probe = {**case, "witness": "probe", "outcome": "allow", "ref": "p"}
    hubble = {**case, "witness": "hubble", "outcome": "allow", "ref": "h"}
    assert assess(case, [probe, hubble]) == ("confirmed", ("p", "h"))
    assert assess(case, [probe, {**hubble, "outcome": "deny"}]) == ("disagreement", ("p", "h"))
    assert assess(case, [probe, {**hubble, "run": "old"}])[0] == "incomplete"
