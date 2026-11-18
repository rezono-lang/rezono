import pytest

from offline_cases import PLAN_HASH, relation


def test_dispatch_policy():
    names = ("plan_hash", "approval_hash", "currency", "approval_currency", "decision",
             "cost_micros", "cap_micros", "event_us", "expires_us")
    base = (PLAN_HASH, PLAN_HASH, "USD", "USD", "approve", 1614000, 1614000, 9, 10)
    variants = {"equal_cap": {}, "below_cap": {"cap_micros": 1620000},
                "wrong_hash": {"approval_hash": "b" * 64}, "declined": {"decision": "decline"},
                "expired": {"event_us": 10}, "late": {"event_us": 11},
                "over_cap": {"cap_micros": 1613999}, "currency": {"approval_currency": "EUR"},
                "missing_cost": {"cost_micros": None}, "no_expiry": {"expires_us": None}}
    facts = {"candidate": [(key,) for key in variants]}
    for key, overrides in variants.items():
        for name, default in zip(names, base):
            value = overrides.get(name, default)
            if value is not None:
                facts.setdefault("candidate__" + name, []).append((key, value))
    assert relation("dispatch", facts, "authorized") == {("equal_cap",), ("below_cap",)}
