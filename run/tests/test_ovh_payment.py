"""Pay one order exactly once, per decisions/run-price-enforcement.md, Correlation."""

import pytest

from offline_cases import implementation


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-price-enforcement.md, Correlation. Implement pay(call, order_id, payment_method_id) in "
    "run/ovh_payment.py; call(method, path, body) is the provider port."
))
def test_ovh_payment():
    pay = implementation("ovh_payment.py", "pay")
    calls = []

    def answered(method, path, body):
        calls.append((method, path, body))
        return None

    assert pay(answered, 4711, 31) == ("submitted", "4711")
    assert calls == [("POST", "/me/order/4711/pay", {"paymentMethod": {"id": 31}})]

    def lost(method, path, body):
        calls.append((method, path, body))
        raise TimeoutError("no response")

    # A lost response is resolved by the status of the same order, never by a second payment.
    calls.clear()
    assert pay(lost, 4711, 31) == ("unresolved", "4711")
    assert calls == [("POST", "/me/order/4711/pay", {"paymentMethod": {"id": 31}})]

    for order_id, method_id in ((0, 31), (-1, 31), ("4711", 31), (True, 31), (4711, None), (4711, "31")):
        calls.clear()
        with pytest.raises(ValueError):
            pay(answered, order_id, method_id)
        assert calls == []
