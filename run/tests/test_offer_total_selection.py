"""Compare provider-backed orders through the shipped offer-selection rules."""

from fractions import Fraction

import pytest

from offline_cases import RUN, relation


def add(facts, kind, key, **fields):
    facts.setdefault(kind, []).append((key,))
    for column, value in fields.items():
        if value is not None:
            facts.setdefault(f"{kind}__{column}", []).append((key, value))


def bids(amber=501, *, estimate=False, blue_evidence=None):
    facts = {}
    add(facts, "demand", "order", quantity=1, billed_periods=2, boot="disk", currency="EUR")
    offers = [("amber", amber, 300, 0, "binding_quote"),
              ("blue", 600, 100, 1, "reject_above")]
    if estimate:
        offers.append(("clear", 1, 0, 2, "estimate"))
    for offer, price, setup, rank, mode in offers:
        provider = f"provider-{offer}"
        add(facts, "offer", offer, provider=provider, price_micros=price, setup_price_micros=setup,
            tie_rank=rank, stock=2, free_disks=1, virtualization="observed", boot="disk", currency="EUR")
        confirmed = {"demand": "order", "offer": offer, "provider": provider, "currency": "EUR",
                     "mode": mode, "scope": "whole_order", "total_micros": int(2 * Fraction(price) + setup)}
        if offer == "blue":
            confirmed.update(blue_evidence or {})
        add(facts, "guarantee", f"receipt-{offer}", **confirmed)
    return facts


@pytest.mark.parametrize(("amber", "winner"), [(499, "amber"), (500, "amber"), (501, "blue")])
def test_selects_the_whole_order(amber, winner):
    assert relation("offer-selection", bids(amber), "selected") == {("order", winner)}


def test_an_estimate_cannot_undercut_a_binding_total():
    assert relation("offer-selection", bids(estimate=True), "selected") == {("order", "blue")}


@pytest.mark.parametrize("change", [
    {"total_micros": 1200}, {"total_micros": None}, {"scope": "period"}, {"mode": "estimate"},
    {"provider": "provider-amber"}, {"demand": "other-order"}, {"offer": "unrelated"},
    {"currency": "USD"},
])
def test_the_guarantee_must_cover_this_exact_order(change):
    assert relation("offer-selection", bids(blue_evidence=change), "selected") == {("order", "amber")}


def test_legacy_unit_rates_alone_cannot_prove_a_choice():
    facts = {k: v for k, v in bids().items() if not k.startswith("guarantee")}
    assert relation("offer-selection", facts, "selected") == set()



def test_selection_proof_accounts_for_every_candidate():
    from rezono_compiler import batch, explain, pack, rules, trace

    program = rules.load(pack.read(RUN / "packs" / "offer-selection").rules)
    with batch.connect(program, bids(estimate=True)) as connection:
        batch.compute(connection, program, witnesses=True)
        snapshots = batch.read(connection, program, program.base_used()) | batch.read(connection, program)
        witnesses = explain.Explainer(program, snapshots, batch.witnesses(connection, program)).chosen()
        steps = trace.steps(program, witnesses, snapshots)

    key = explain.key_text
    assert {(relation, premise, position) for head, selected, relation, premise, how, position in steps
            if head == "selected" and selected == key(("order", "blue")) and how == "contributes"} == {
        ("offer", key(("amber",)), 0),
        ("offer", key(("blue",)), 0),
        ("offer", key(("clear",)), 0),
        ("comparison", key(("order", "blue", "amber", "1302", "0")), 1),
        ("comparison", key(("order", "blue", "blue", "1300", "1")), 1),
        ("excluded", key(("order", "clear")), 2),
    }
    assert {(head, conclusion, premise) for head, conclusion, relation, premise, how, _ in steps
            if head == "confirmed_total" and relation == "guarantee" and how == "positive"} == {
        ("confirmed_total", key(("order", "amber", "1302")), key(("receipt-amber",))),
        ("confirmed_total", key(("order", "blue", "1300")), key(("receipt-blue",))),
    }
