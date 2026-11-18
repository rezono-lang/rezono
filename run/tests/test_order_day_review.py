from datetime import datetime, timedelta, timezone
from fractions import Fraction
from hashlib import sha256
import json

import pytest

from offline_cases import implementation


DAY = "2032-05-03"
NOW = "2032-05-03T08:00:00Z"
END = "2032-05-04T00:00:00Z"
LINES = [{"sku": "demo", "currency": "USD", "quantity": 2, "billed_periods": 3, "setup_price_micros": 250000}]


def source(day, name, body):
    return {"from_day": day, "url": "https://quotes.example.org/" + name, "body": body,
            "sha256": sha256(body).hexdigest()}


BEFORE = source("2032-05-01", "before", b'{"plans_metal":[{"id":"demo","hourly_cost":1.50}]}')
AFTER = source(DAY, "after", b'{"plans_metal":[{"id":"demo","hourly_cost":1.75}]}')
RATE = source("2032-05-01", "rate", b'{"base":"USD","quote":"EUR","n":4,"d":5}')


def test_order_day_review_reference():
    totals = [2 * (3 * rate + Fraction(1, 4)) for rate in (Fraction(3, 2), Fraction(7, 4))]
    assert totals == [Fraction(19, 2), 11]
    assert [cost * Fraction(4, 5) for cost in totals] == [Fraction(38, 5), Fraction(44, 5)]
    assert datetime.fromisoformat(DAY).replace(tzinfo=timezone.utc) + timedelta(days=1) == datetime.fromisoformat(END)


def test_order_day_review():
    plan = implementation("order_day_review.py", "plan")
    review = implementation("order_day_review.py", "review")
    prices = [AFTER, BEFORE]
    original = plan(DAY, LINES, [BEFORE], [RATE], "paper")
    revised = plan(DAY, LINES, prices, [RATE], "paper")
    for raw, usd, eur, price in [(original, [19, 2], [38, 5], BEFORE), (revised, [11, 1], [44, 5], AFTER)]:
        data = json.loads(raw)
        assert (data["order_day"], data["usd"], data["eur"]) == (DAY, usd, eur)
        assert (data["price_source"], data["fx_source"]) == (price["sha256"], RATE["sha256"])
    old_hash, new_hash = [sha256(raw).hexdigest() for raw in (original, revised)]
    assert old_hash != new_hash
    approval = {"plan_hash": old_hash, "decision": "approve", "budget_cents": 900,
                "currency": "EUR", "expires_at": "2032-05-05T12:00:00Z"}
    quote = {"provider": "paper", "mode": "binding_quote", "total_usd": [11, 1], "includes_setup": True,
             "expires_at": "2032-05-04T12:00:00Z", "reference": "paper-7"}

    def check(consent, guarantee, now=NOW):
        return review(consent, now, DAY, LINES, prices, [RATE], guarantee)

    assert check(approval, quote) == {"reason": "renew_approval", "candidate_hash": new_hash, "request": None}
    renewed = dict(approval, plan_hash=new_hash)
    for mode in ("binding_quote", "reject_above"):
        checked = check(renewed, dict(quote, mode=mode))
        assert checked == {"reason": "authorized", "candidate_hash": new_hash,
                           "request": {"plan_hash": new_hash, "provider": "paper", "mode": mode,
                                       "reference": "paper-7", "currency": "USD", "max_total": [11, 1], "expires_at": END}}
    early = "2032-05-03T13:00:00Z"
    assert check(renewed, dict(quote, expires_at=early))["request"]["expires_at"] == early
    assert check(dict(renewed, expires_at=early), quote)["request"]["expires_at"] == early
    for consent, guarantee, moment, reason in [
        (renewed, quote, "2032-05-04T01:00:00+01:00", "expired"),
        (renewed, dict(quote, expires_at=NOW), NOW, "expired"),
        (dict(renewed, budget_cents=879), quote, NOW, "over_cap"),
        (renewed, dict(quote, includes_setup=False), NOW, "unbound_total"),
        (renewed, dict(quote, mode="estimate"), NOW, "unbound_total"),
        (renewed, dict(quote, total_usd=[45, 4]), NOW, "unbound_total"),
    ]:
        rejected = check(consent, guarantee, moment)
        assert (rejected["reason"], rejected["request"]) == (reason, None)
