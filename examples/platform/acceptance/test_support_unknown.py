import pytest

from query_fixture import check_relation, evidence


def test_support_unknown():
    rows, _ = evidence()
    expected = {(*row, "unknown") for row in rows["runs"]}
    assert len(expected) == 3
    check_relation("support_unknown", expected)
