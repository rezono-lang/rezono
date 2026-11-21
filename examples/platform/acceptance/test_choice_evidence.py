import pytest

from query_fixture import check_relation, evidence


def test_choice_evidence():
    rows, facts = evidence()
    product = {r["id"]: r["product"] for r in facts["service"]}
    expected = {(a, b, f, port, choice["id"], offer["id"]) for a, b, f, port in rows["flow"]
                for choice in facts["choice"] if (a, f, b) == (choice["service"], choice["function"], choice["provider"])
                for offer in facts["offer"]
                if (product[b], f) == (offer["product"], offer["function"]) and offer.get("port", port) == port}
    assert len(expected) == 2
    check_relation("choice_evidence", expected)
