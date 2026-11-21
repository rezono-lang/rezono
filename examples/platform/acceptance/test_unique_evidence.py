from query_fixture import check_relation, evidence, reads_offer_port


def test_unique_evidence():
    rows, facts = evidence()
    products = {r["id"]: r["product"] for r in facts["service"]}
    chosen = {(r["service"], r["function"]) for r in facts["choice"]}
    implicit_flows = [(a, b, f, port) for a, b, f, port in rows["flow"] if (a, f) not in chosen]
    assert len(implicit_flows) == 34
    if reads_offer_port("unique_evidence"):
        expected = {
            (a, b, f, port, demand["id"], offer["id"])
            for a, b, f, port in implicit_flows
            for demand in facts["demand"]
            if (products[a], f) == (demand["product"], demand["function"])
            for offer in facts["offer"]
            if (products[b], f, port) == (offer["product"], offer["function"], offer["port"])
        }
        assert len(expected) == 34
    else:
        # Once unique_evidence reads derived provides(b, f, p) instead of offer__port(o, p)
        # (decisions/platform-facts-not-conclusions.md, section 3), offers match by (product, function).
        # While core.yaml retains both Forgejo git offers (o-git-https and o-git-ssh) until Offer.port
        # retires, each of the 4 implicit git flows pairs with both offers (38 rows); unifying those
        # two offers returns the count to 34.
        provides = {tuple(row) for row in rows["provides"]}
        expected = {
            (a, b, f, port, demand["id"], offer["id"])
            for a, b, f, port in implicit_flows
            if (b, f, port) in provides
            for demand in facts["demand"]
            if (products[a], f) == (demand["product"], demand["function"])
            for offer in facts["offer"]
            if (products[b], f) == (offer["product"], offer["function"])
        }
        assert len(expected) in (34, 38)
        assert len(expected) == sum(
            sum(1 for offer in facts["offer"] if (products[b], f) == (offer["product"], offer["function"]))
            for _, b, f, _ in implicit_flows
        )
    check_relation("unique_evidence", expected)
