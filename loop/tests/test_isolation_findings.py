"""Distinguish unintended boundary allowances from service isolation."""

import pytest

from wire_fixtures import entry, fixture


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-fixture-evidence.md. Implement loop/isolation_findings.py. Distinguish unintended boundary allowances from service isolation.")
def test_isolation_findings(monkeypatch):
    findings = entry(monkeypatch, "isolation_findings", "findings")
    net = fixture("network")
    cases = net["cases"]
    witness = [{"case": c["id"], "layer": layer, "verdict": c[layer], "ref": f"{layer}/{c['id']}"}
               for c in cases for layer in ("service", "router") if c[layer] != "inapplicable"]
    assert findings(cases, witness) == []
    broken = [{**w, "verdict": "deny"} if (w["case"], w["layer"]) == ("echo", "router") else w for w in witness]
    assert findings(cases, broken) == [{"case": "echo", "layer": "router", "expected": "allow",
                                       "observed": "deny", "evidence": "router/echo"}]
