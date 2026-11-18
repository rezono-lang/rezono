import pytest

from query_fixture import check_relation, evidence


def test_recovery_rule_delta():
    rows, _ = evidence()
    zones = dict(rows["zone_of"])
    blocked = set(map(tuple, rows["recovery_reaches_out"]))
    def project(flows):
        return {(zones[a], zones[b], port) for a, b, _, port in flows if zones[a] != zones[b]}
    after = project(rows["flow"])
    before = project(row for row in rows["flow"] if tuple(row[:3]) not in blocked)
    expected = {("added", *row) for row in after - before} | {("removed", *row) for row in before - after}
    assert expected == {("added", "recovery", "platform", 8443)}
    check_relation("recovery_rule_delta", expected)
