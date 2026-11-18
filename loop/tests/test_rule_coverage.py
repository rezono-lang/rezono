"""Account for each logical rule with a registered positive witness."""

from wire_fixtures import entry, fixture


def test_rule_coverage(monkeypatch):
    coverage = entry(monkeypatch, "rule_coverage", "coverage")
    net = fixture("network")
    result = coverage(net["endpoints"], net["rules"], net["cases"])
    echo, peer = net["rules"]
    assert result == [
        {"rule": echo, "caseIds": ["echo", "upper"]},
        {"rule": peer, "caseIds": ["other-rule"]},
    ]
    extra = dict(net["rules"][0], function="same-packet")
    assert coverage(net["endpoints"], [*net["rules"], extra], net["cases"]) == [
        *result, {"rule": extra, "caseIds": ["echo", "upper"]},
    ]


def test_same_function_keeps_the_unprobed_rule_separate(monkeypatch):
    coverage = entry(monkeypatch, "rule_coverage", "coverage")
    net = fixture("network")
    echo, peer = net["rules"]
    unprobed = dict(echo, fromPort=8082, toPort=8082)

    expected = [
        {"rule": echo, "caseIds": ["echo", "upper"]},
        {"rule": unprobed, "caseIds": []},
        {"rule": peer, "caseIds": ["other-rule"]},
    ]
    assert coverage(net["endpoints"], [echo, unprobed, peer], net["cases"]) == expected
    assert coverage(net["endpoints"], [peer, unprobed, echo], reversed(net["cases"])) == expected
