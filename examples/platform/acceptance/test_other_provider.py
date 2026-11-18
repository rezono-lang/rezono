import pytest

from query_fixture import check_relation, evidence


def test_other_provider():
    rows, facts = evidence()
    expected = {(choice["service"], b, f, choice["provider"], choice["id"])
                for choice in facts["choice"] for b, f, _ in rows["provides"]
                if f == choice["function"] and b != choice["provider"]}
    assert len(expected) == 2
    check_relation("other_provider", expected)
