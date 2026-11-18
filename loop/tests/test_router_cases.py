"""Classify only the registered cases against the union of allowances."""

import pytest

from wire_fixtures import entry, fixture


def test_router_cases(monkeypatch):
    router_verdicts = entry(monkeypatch, "router_cases", "router_verdicts")
    net = fixture("network")
    expected = {c["id"]: c["router"] for c in net["cases"]}
    inputs = [{k: v for k, v in case.items() if k not in {"router", "service"}} for case in net["cases"]]
    for rules in (net["rules"], list(reversed(net["rules"]))):
        assert router_verdicts(net["endpoints"], rules, inputs) == expected
    assert router_verdicts(net["endpoints"], [], inputs) == {
        key: "inapplicable" if key == "local" else "deny" for key in expected}
