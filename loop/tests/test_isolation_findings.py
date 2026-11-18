"""Distinguish unintended boundary allowances from service isolation."""

from wire_fixtures import entry, fixture


def test_isolation_findings(monkeypatch):
    findings = entry(monkeypatch, "isolation_findings", "findings")
    net = fixture("network")
    cases = net["cases"]
    witness = fixture("isolation_observations")
    assert findings(cases, witness) == []
    broken = [{**w, "verdict": "deny"} if (w["case"], w["layer"]) == ("echo", "router") else w for w in witness]
    assert findings(cases, broken) == [{"case": "echo", "layer": "router", "expected": "allow",
                                       "observed": "deny", "evidence": "router/echo"}]


def test_changed_expectation_keeps_the_recorded_verdict(monkeypatch):
    findings = entry(monkeypatch, "isolation_findings", "findings")
    cases = fixture("network")["cases"]
    changed_cases = [dict(case, router="deny") if case["id"] == "echo" else case for case in cases]
    observations = fixture("isolation_observations")
    assert findings(changed_cases, observations) == [
        {"case": "echo", "layer": "router", "expected": "deny", "observed": "allow", "evidence": "router/echo"}
    ]
