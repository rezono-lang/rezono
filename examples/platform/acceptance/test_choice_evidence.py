import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Expose the authored choice and matching offer supporting each explicitly routed flow. Read decisions/platform-query-results.md. Write examples/platform/rules/choice_evidence.dl and its own module-specific metadata if needed.")
def test_choice_evidence():
    rows, facts = evidence()
    product = {r["id"]: r["product"] for r in facts["service"]}
    expected = {(a, b, f, port, choice["id"], offer["id"]) for a, b, f, port in rows["flow"]
                for choice in facts["choice"] if (a, f, b) == (choice["service"], choice["function"], choice["provider"])
                for offer in facts["offer"] if (product[b], f, port) == (offer["product"], offer["function"], offer["port"])}
    assert len(expected) == 2
    check_relation("choice_evidence", expected)
