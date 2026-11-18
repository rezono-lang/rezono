import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Project both recovery scenarios to boundary rules before computing their difference. Read decisions/platform-query-results.md. Write examples/platform/rules/recovery_rule_delta.dl and its own module-specific metadata if needed.")
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
