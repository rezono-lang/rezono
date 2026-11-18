import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Explain why a capable provider was bypassed when an explicit choice names another service. Read decisions/platform-query-results.md. Write examples/platform/rules/other_provider.dl and its own module-specific metadata if needed.")
def test_other_provider():
    rows, facts = evidence()
    expected = {(choice["service"], b, f, choice["provider"], choice["id"])
                for choice in facts["choice"] for b, f, _ in rows["provides"]
                if f == choice["function"] and b != choice["provider"]}
    assert len(expected) == 2
    check_relation("other_provider", expected)
