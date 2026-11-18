"""Account for each logical rule with a registered positive witness."""

import pytest

from wire_fixtures import entry, fixture


def test_rule_coverage(monkeypatch):
    coverage = entry(monkeypatch, "rule_coverage", "coverage")
    net = fixture("network")
    result = coverage(net["endpoints"], net["rules"], net["cases"])
    assert result == {"echo": ["echo", "upper"], "peer": ["other-rule"]}
    extra = dict(net["rules"][0], function="same-packet")
    assert coverage(net["endpoints"], [*net["rules"], extra], net["cases"]) == {
        **result, "same-packet": ["echo", "upper"]}
