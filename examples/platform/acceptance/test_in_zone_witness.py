import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Retain the service and capability evidence for each same-zone policy allowance. Read decisions/platform-query-results.md. Write examples/platform/rules/in_zone_witness.dl and its own module-specific metadata if needed.")
def test_in_zone_witness():
    rows, _ = evidence()
    zones = dict(rows["zone_of"])
    expected = {(zones[a], a, b, fn, port) for a, b, fn, port in rows["flow"] if zones[a] == zones[b]}
    assert len(expected) == 15
    check_relation("in_zone_witness", expected)
