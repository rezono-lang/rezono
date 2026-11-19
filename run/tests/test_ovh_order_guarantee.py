"""Read an unpaid provider order as a binding quote, per decisions/run-price-enforcement.md.

The expected totals are computed by hand from integer microcents (10^-8 of the currency unit).
"""

from copy import deepcopy

import pytest

from offline_cases import implementation

PLAN = "a" * 64
DAY = "2032-05-04"


def price(ucents, value=None):
    return {"currencyCode": "EUR", "priceInUcents": ucents,
            "value": ucents / 10**8 if value is None else value, "text": f"{ucents} uc"}


def order():
    return {
        "orderId": 4711, "url": "https://order.example.org/4711", "contracts": [],
        "details": [
            {"cartItemID": 1, "description": "setup", "detailType": "INSTALLATION", "domain": "*",
             "quantity": 1, "unitPrice": price(4999000000), "totalPrice": price(4999000000)},
            {"cartItemID": 1, "description": "first month", "detailType": "DURATION", "domain": "*",
             "quantity": 1, "unitPrice": price(8999000000), "totalPrice": price(8999000000)},
        ],
        # 49.99 + 89.99 = 139.98 without tax; 20 % tax is 27.996; with tax 167.976 = 20997/125.
        "prices": {"withoutTax": price(13998000000), "tax": price(2799600000),
                   "withTax": price(16797600000, value=167.97600000000003)},
    }


def record():
    return {"orderId": 4711, "date": "2032-05-04T09:00:00+02:00",
            "expirationDate": "2032-05-05T01:30:00+02:00", "priceWithTax": price(16797600000)}


@pytest.mark.xfail(strict=True, reason=(
    "M4: decisions/run-price-enforcement.md: Read the section Conditions for the OVHcloud guarantee. "
    "Implement guarantee(order, record, plan_hash, day) in run/ovh_order.py."
))
def test_ovh_order_guarantee():
    guarantee = implementation("ovh_order.py", "guarantee")

    expected = {"mode": "binding_quote", "currency": "EUR", "total": [20997, 125], "includes_setup": True,
                "expires_at": "2032-05-04T23:30:00Z", "reference": "4711", "plan_hash": PLAN}
    assert guarantee(order(), record(), PLAN, DAY) == expected
    # A later order expiry is still cut at the next UTC midnight of the approved day.
    later = dict(record(), expirationDate="2032-05-12T00:00:00+02:00")
    assert guarantee(order(), later, PLAN, DAY) == dict(expected, expires_at="2032-05-05T00:00:00Z")

    def refused(change, match, target="order"):
        bodies = {"order": order(), "record": record()}
        change(bodies[target])
        with pytest.raises(ValueError, match=match):
            guarantee(bodies["order"], bodies["record"], PLAN, DAY)

    def usage(body, kind):
        body["details"].append(dict(deepcopy(body["details"][1]), detailType=kind, totalPrice=price(0)))

    # Usage-billed lines are outside any bound, even at zero.
    refused(lambda body: usage(body, "CONSUMPTION"), "usage")
    refused(lambda body: usage(body, "OUTPLAN"), "usage")
    # Independent arithmetic: details, tax and total must agree.
    refused(lambda body: body["details"][0].update(totalPrice=price(4999000001)), "details")
    refused(lambda body: body["prices"].update(tax=price(2799600001)), "tax")
    # The exact integer is required; the floating-point value never substitutes for it.
    refused(lambda body: body["prices"]["withTax"].pop("priceInUcents"), "priceInUcents")
    refused(lambda body: body["prices"]["withTax"].update(priceInUcents=True), "priceInUcents")
    refused(lambda body: body["details"][1]["totalPrice"].update(currencyCode="USD"), "currency")
    refused(lambda body: body.update(orderId=4712), "order id", "record")
    refused(lambda body: body.update(priceWithTax=price(16797600001)), "record", "record")
    refused(lambda body: body.pop("expirationDate"), "expiration", "record")
    refused(lambda body: body.update(expirationDate="2032-05-05T01:30:00"), "expiration", "record")
    with pytest.raises(ValueError, match="plan hash"):
        guarantee(order(), record(), "A" * 64, DAY)
