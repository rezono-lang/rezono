"""Reject malformed packet rules before producing an artifact."""

import pytest

from wire_fixtures import entry, fixture


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-fixture-evidence.md. Implement loop/router_preflight.py. Reject malformed packet rules before producing an artifact.")
def test_router_preflight(monkeypatch):
    validate = entry(monkeypatch, "router_preflight", "validate")
    rules = fixture("network")["rules"]
    assert validate(rules) is None
    for change in ({"fromPort": 8082}, {"sourceFrom": -1}, {"destinationAddress": 2**32},
                   {"protocol": "guess"}, {"toPort": True}, {"unknownField": "unexpected"}):
        with pytest.raises(ValueError):
            validate([rules[0], dict(rules[1], **change)])
