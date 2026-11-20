"""Create an unpaid order through a recorded transport, per decisions/run-price-enforcement.md."""

import pytest

from offline_cases import implementation

PLAN = "b" * 64
REQUEST = {
    "subsidiary": "FR", "plan_code": "example-plan", "duration": "P1M", "pricing_mode": "default", "quantity": 1,
    "configuration": {"region": "europe", "dedicated_os": "none_64.en", "dedicated_datacenter": "example-dc"},
    "plan_hash": PLAN, "expire": "2032-05-05T00:00:00Z", "waive_retraction": False,
}


def total(ucents):
    return {"withTax": {"currencyCode": "EUR", "priceInUcents": ucents}}


class Recorded:
    """A recorded provider: answers each call in order and keeps what was asked."""

    def __init__(self, created=16797600000):
        self.calls = []
        self.answers = [{"cartId": "cart-1"}, None, {"cartId": "cart-1", "itemId": 7}, {}, {}, {},
                        {"orderId": 0, "prices": total(16797600000)},
                        {"orderId": 4711, "prices": total(created)}]

    def __call__(self, method, path, body):
        self.calls.append((method, path, body))
        return self.answers[len(self.calls) - 1]


def test_ovh_checkout():
    checkout = implementation("ovh_checkout.py", "checkout")

    provider = Recorded()
    assert checkout(provider, REQUEST) == {"orderId": 4711, "prices": total(16797600000)}
    cart = "/order/cart/cart-1"
    assert provider.calls == [
        ("POST", "/order/cart", {"ovhSubsidiary": "FR", "description": PLAN, "expire": "2032-05-05T00:00:00Z"}),
        ("POST", f"{cart}/assign", None),
        ("POST", f"{cart}/baremetalServers",
         {"planCode": "example-plan", "duration": "P1M", "pricingMode": "default", "quantity": 1}),
        ("POST", f"{cart}/item/7/configuration", {"label": "dedicated_datacenter", "value": "example-dc"}),
        ("POST", f"{cart}/item/7/configuration", {"label": "dedicated_os", "value": "none_64.en"}),
        ("POST", f"{cart}/item/7/configuration", {"label": "region", "value": "europe"}),
        ("GET", f"{cart}/checkout", None),
        ("POST", f"{cart}/checkout", {"autoPayWithPreferredPaymentMethod": False, "waiveRetractationPeriod": False}),
    ]
    # Nothing is ever paid here.
    assert not any("/pay" in path for _, path, _ in provider.calls)

    # A created order that differs from the checkout read is no quote.
    with pytest.raises(ValueError, match="checkout"):
        checkout(Recorded(created=16797600001), REQUEST)
    # The retraction choice is the requester's, never a default.
    for broken in ({k: v for k, v in REQUEST.items() if k != "waive_retraction"}, dict(REQUEST, plan_hash="plan")):
        with pytest.raises(ValueError):
            checkout(Recorded(), broken)
