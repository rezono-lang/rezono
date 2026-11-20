"""Pay one order exactly once, per decisions/run-price-enforcement.md, Correlation."""

import pytest

from offline_cases import implementation


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
