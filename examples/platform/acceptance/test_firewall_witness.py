import pytest

from query_fixture import check_relation, evidence


def test_firewall_witness():
    rows, _ = evidence()
    zones = dict(rows["zone_of"])
    expected = {(zones[a], zones[b], port, a, b, fn) for a, b, fn, port in rows["flow"] if zones[a] != zones[b]}
    assert len(expected) == 21
    check_relation("firewall_witness", expected)
