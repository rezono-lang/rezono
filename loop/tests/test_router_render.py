"""Render deterministic router bytes while retaining distinct logical rule witnesses."""

import pytest

from wire_fixtures import entry, fixture


def test_router_render(monkeypatch):
    render = entry(monkeypatch, "router_render", "render")
    net = fixture("network")
    rules = net["rules"]
    artifact = render(rules)
    assert isinstance(artifact, bytes)
    assert artifact.endswith(b"\n") and b"\r" not in artifact
    assert render(list(reversed(rules))) == render([*rules, rules[0]]) == artifact
    text = artifact.decode("utf-8")
    assert "policy drop" in text
    assert "192.0.2.17" in text and "192.0.2.18" in text
    for name in ("echo", "peer"):
        assert any(name in line and "accept" in line for line in text.splitlines())
    assert artifact != render([dict(rules[0], toPort=8080), rules[1]])
