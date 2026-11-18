"""Hand-calculated reference for the captured public prices and synthetic bill."""

from fractions import Fraction
from hashlib import sha256
import json

from offline_cases import FIXTURE, PLAN_HASH, PRICE_FACTS_HASH, PRICE_SOURCE_HASH


def test_public_price_arithmetic_offline():
    price_bytes = (FIXTURE / "price-facts.json").read_bytes()
    plan_bytes = (FIXTURE / "plan.json").read_bytes()
    assert sha256(price_bytes).hexdigest() == PRICE_FACTS_HASH
    assert sha256(plan_bytes).hexdigest() == PLAN_HASH
    response = json.loads(price_bytes, parse_float=Fraction)
    prices = {row["id"]: row["hourly_cost"] for row in response["plans_metal"]}
    plan = json.loads(plan_bytes)
    assert plan["price_source_sha256"] == PRICE_SOURCE_HASH
    assert plan["price_facts_sha256"] == PRICE_FACTS_HASH
    assert prices == {"vbm-4c-32gb": Fraction(164, 1000), "vbm-8c-132gb": Fraction(479, 1000)}
    total = sum(prices[line["sku"]] * line["quantity"] * line["billed_periods"]
                for line in plan["lines"])
    assert total == Fraction(807, 500)
    assert 161 * 10_000 < total * 1_000_000 == 1_614_000 <= 162 * 10_000
