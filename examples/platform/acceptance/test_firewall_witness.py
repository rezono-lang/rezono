import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Attach each contributing service and function to the summarised boundary rule. Read decisions/platform-query-results.md. Write examples/platform/rules/firewall_witness.dl and its own module-specific metadata if needed.")
def test_firewall_witness():
    rows, _ = evidence()
    zones = dict(rows["zone_of"])
    expected = {(zones[a], zones[b], port, a, b, fn) for a, b, fn, port in rows["flow"] if zones[a] != zones[b]}
    assert len(expected) == 21
    check_relation("firewall_witness", expected)
