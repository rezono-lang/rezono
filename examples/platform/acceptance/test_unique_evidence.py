import pytest

from query_fixture import check_relation, evidence


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Explain implicit provider selection with the demand and matching offer identifiers. Read decisions/platform-query-results.md. Write examples/platform/rules/unique_evidence.dl and its own module-specific metadata if needed.")
def test_unique_evidence():
    rows, facts = evidence()
    products = {r["id"]: r["product"] for r in facts["service"]}
    chosen = {(r["service"], r["function"]) for r in facts["choice"]}
    expected = {(a, b, f, port, demand["id"], offer["id"]) for a, b, f, port in rows["flow"]
                if (a, f) not in chosen for demand in facts["demand"] if (products[a], f) == (demand["product"], demand["function"])
                for offer in facts["offer"] if (products[b], f, port) == (offer["product"], offer["function"], offer["port"])}
    assert len(expected) == 34
    check_relation("unique_evidence", expected)
