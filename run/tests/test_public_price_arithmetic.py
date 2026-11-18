"""Hand-calculated reference for the captured public prices and synthetic bill."""

from fractions import Fraction
from hashlib import sha256
import json

from offline_cases import FIXTURE, PLAN_HASH, SOURCE


def test_public_price_arithmetic_offline():
    price_bytes = (FIXTURE / "public-price-response.json").read_bytes()
    plan_bytes = (FIXTURE / "plan.json").read_bytes()
    assert sha256(price_bytes).hexdigest() == SOURCE
    assert sha256(plan_bytes).hexdigest() == PLAN_HASH
    response = json.loads(price_bytes, parse_float=Fraction)
    assert response["meta"]["total"] > len(response["plans_metal"])
    assert response["meta"]["links"]["next"]
    prices = {row["id"]: row["hourly_cost"] for row in response["plans_metal"]}
    plan = json.loads(plan_bytes)
    assert plan["price_source_sha256"] == SOURCE
    total = sum(prices[line["sku"]] * line["quantity"] * line["billed_periods"]
                for line in plan["lines"])
    assert total == Fraction(807, 500)
    assert 161 * 10_000 < total * 1_000_000 == 1_614_000 <= 162 * 10_000
