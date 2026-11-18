import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Report an unknown support date for every running release lacking vendor evidence. Read decisions/platform-query-results.md. Write examples/platform/rules/support_unknown.dl and its own module-specific metadata if needed.")
def test_support_unknown():
    rows, _ = evidence()
    expected = {(*row, "unknown") for row in rows["runs"]}
    assert len(expected) == 3
    check_relation("support_unknown", expected)
