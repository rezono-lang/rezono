import pytest

from offline_cases import implementation, PLAN_HASH


def test_order_uncertainty():
    apply = implementation("order_uncertainty.py", "invoke")
    events = []
    occupied = set()
    receipt = {"id": "one", "plan_hash": PLAN_HASH}
    def claim(key):
        events.append(("claim", key))
        if key in occupied:
            return False
        occupied.add(key)
        return True
    def dispatch(key):
        assert key in occupied
        events.append(("apply", key))
        raise TimeoutError("response lost")
    def status(key):
        events.append(("status", key))
        return receipt
    assert apply(PLAN_HASH, claim, dispatch, status) == ("applied", receipt)
    assert apply(PLAN_HASH, claim, dispatch, lambda _: None) == ("unknown", None)
    assert events == [("claim", PLAN_HASH), ("apply", PLAN_HASH), ("status", PLAN_HASH), ("claim", PLAN_HASH)]
    wrong = {"id": "wrong", "plan_hash": "b" * 64}
    assert apply(PLAN_HASH, claim, dispatch, lambda _: wrong) == ("unknown", None)
