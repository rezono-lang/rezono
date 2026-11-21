from query_fixture import check_relation, evidence, reads_offer_port


def test_choice_evidence():
    rows, facts = evidence()
    product = {r["id"]: r["product"] for r in facts["service"]}
    if reads_offer_port("choice_evidence"):
        expected = {
            (a, b, f, port, choice["id"], offer["id"])
            for a, b, f, port in rows["flow"]
            for choice in facts["choice"]
            if (a, f, b) == (choice["service"], choice["function"], choice["provider"])
            for offer in facts["offer"]
            if (product[b], f, port) == (offer["product"], offer["function"], offer["port"])
        }
    else:
        # Once choice_evidence reads derived provides(b, f, p) instead of offer__port(o, p)
        # (decisions/platform-facts-not-conclusions.md, section 3), offers match by (product, function).
        provides = {tuple(row) for row in rows["provides"]}
        expected = {
            (a, b, f, port, choice["id"], offer["id"])
            for a, b, f, port in rows["flow"]
            for choice in facts["choice"]
            if (a, f, b) == (choice["service"], choice["function"], choice["provider"])
            for offer in facts["offer"]
            if (b, f, port) in provides and (product[b], f) == (offer["product"], offer["function"])
        }
    assert len(expected) == 2
    check_relation("choice_evidence", expected)
