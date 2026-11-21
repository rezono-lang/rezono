import pytest

from query_fixture import check_relation, evidence


def test_unique_evidence():
    rows, facts = evidence()
    products = {r["id"]: r["product"] for r in facts["service"]}
    chosen = {(r["service"], r["function"]) for r in facts["choice"]}
    expected = {(a, b, f, port, demand["id"], offer["id"]) for a, b, f, port in rows["flow"]
                if (a, f) not in chosen for demand in facts["demand"] if (products[a], f) == (demand["product"], demand["function"])
                for offer in facts["offer"]
                if (products[b], f) == (offer["product"], offer["function"]) and offer.get("port", port) == port}
    assert len(expected) == 34
    check_relation("unique_evidence", expected)
