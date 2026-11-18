import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Compute the exact added and removed flow tuples when recovery isolation is relaxed. Read decisions/platform-query-results.md. Write examples/platform/rules/recovery_flow_delta.dl and its own module-specific metadata if needed.")
def test_recovery_flow_delta():
    rows, _ = evidence()
    blocked = set(map(tuple, rows["recovery_reaches_out"]))
    requested = set(map(tuple, rows["flow"]))
    before = {row for row in requested if row[:3] not in blocked}
    expected = {("added", *row) for row in requested - before} | {("removed", *row) for row in before - requested}
    assert expected == {("added", "restore-bad", "idp", "identity", 8443)}
    check_relation("recovery_flow_delta", expected)
