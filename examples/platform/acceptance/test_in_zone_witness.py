import pytest

from query_fixture import check_relation, evidence


def test_in_zone_witness():
    rows, _ = evidence()
    zones = dict(rows["zone_of"])
    expected = {(zones[a], a, b, fn, port) for a, b, fn, port in rows["flow"] if zones[a] == zones[b]}
    assert len(expected) == 15
    check_relation("in_zone_witness", expected)
