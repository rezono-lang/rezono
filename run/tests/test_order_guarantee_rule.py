"""Order guarantee policy comes from the provider terms pack: decisions/code-does-not-decide.md.

The expectation is the behaviour of run/ovh_order.py under decisions/run-price-enforcement.md,
"Every charge is in the order" and "Expiry": usage-billed detail types (CONSUMPTION, OUTPLAN)
give no guarantee, otherwise the order yields mode binding_quote expiring at
min(expirationDate, next UTC midnight of the approved day).
"""
import ast
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from offline_cases import RUN, implementation

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PLAN = "a" * 64
DAY = "2032-05-04"
POLICY_LITERALS = {"CONSUMPTION", "OUTPLAN", "binding_quote"}


def utc_us(year, month, day, hour, minute, second=0):
    return (datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc) - EPOCH) // timedelta(microseconds=1)


def literals(name):
    tree = ast.parse((RUN / name).read_text(encoding="utf-8"))
    return {node.value for node in ast.walk(tree) if isinstance(node, ast.Constant) and isinstance(node.value, str)}


def calls_min(name):
    tree = ast.parse((RUN / name).read_text(encoding="utf-8"))
    return any(
        isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "min"
        for node in ast.walk(tree)
    )


def pack_reads(monkeypatch):
    """The (pack, relation, rows) tuples whose derived rows the code reads."""
    from rezono_compiler import batch

    reads = []
    read = batch.read

    def spy(con, prog, names=None):
        rows = read(con, prog, names)
        for name, values in rows.items():
            reads.append((prog.pack, name, set(values)))
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return reads


def price(ucents, value=None):
    return {
        "currencyCode": "EUR",
        "priceInUcents": ucents,
        "value": ucents / 10**8 if value is None else value,
        "text": f"{ucents} uc",
    }


def order():
    return {
        "orderId": 4711,
        "url": "https://order.example.org/4711",
        "contracts": [],
        "details": [
            {
                "cartItemID": 1,
                "description": "setup",
                "detailType": "INSTALLATION",
                "domain": "*",
                "quantity": 1,
                "unitPrice": price(4999000000),
                "totalPrice": price(4999000000),
            },
            {
                "cartItemID": 1,
                "description": "first month",
                "detailType": "DURATION",
                "domain": "*",
                "quantity": 1,
                "unitPrice": price(8999000000),
                "totalPrice": price(8999000000),
            },
        ],
        # 49.99 + 89.99 = 139.98 without tax; 20 % tax is 27.996; with tax 167.976 = 20997/125.
        "prices": {
            "withoutTax": price(13998000000),
            "tax": price(2799600000),
            "withTax": price(16797600000, value=167.97600000000003),
        },
    }


def record():
    return {
        "orderId": 4711,
        "date": "2032-05-04T09:00:00+02:00",
        "expirationDate": "2032-05-05T01:30:00+02:00",
        "priceWithTax": price(16797600000),
    }


def test_order_guarantee_comes_from_provider_terms(monkeypatch):
    assert (RUN / "packs" / "provider-terms" / "pack.yaml").is_file(), "run/packs/provider-terms is missing"
    assert not literals("ovh_order.py") & POLICY_LITERALS, (
        "usage detail types and quote mode are written in code, not in run/packs/provider-terms"
    )
    assert not calls_min("ovh_order.py"), "the expiry bound min(expiration_utc, day_end) is still computed in Python"

    reads = pack_reads(monkeypatch)
    guarantee = implementation("ovh_order.py", "guarantee")

    expected = {
        "mode": "binding_quote",
        "currency": "EUR",
        "total": [20997, 125],
        "includes_setup": True,
        "expires_at": "2032-05-04T23:30:00Z",
        "reference": "4711",
        "plan_hash": PLAN,
    }

    # Order expiring before the next UTC midnight keeps its own expirationDate.
    reads.clear()
    assert guarantee(order(), record(), PLAN, DAY) == expected
    derived = [rows for pack_name, rel, rows in reads if (pack_name, rel) == ("provider-terms", "order_guarantee")]
    assert derived, reads
    assert {(mode, expires) for _, mode, expires in derived[-1]} == {
        ("binding_quote", str(utc_us(2032, 5, 4, 23, 30)))
    }

    # A later order expiry is capped at the next UTC midnight of the approved day by the pack rule.
    later = dict(record(), expirationDate="2032-05-12T00:00:00+02:00")
    reads.clear()
    assert guarantee(order(), later, PLAN, DAY) == dict(expected, expires_at="2032-05-05T00:00:00Z")
    derived = [rows for pack_name, rel, rows in reads if (pack_name, rel) == ("provider-terms", "order_guarantee")]
    assert derived, reads
    assert {(mode, expires) for _, mode, expires in derived[-1]} == {
        ("binding_quote", str(utc_us(2032, 5, 5, 0, 0)))
    }

    # Equality with the next UTC midnight yields that midnight.
    equal = dict(record(), expirationDate="2032-05-05T00:00:00Z")
    reads.clear()
    assert guarantee(order(), equal, PLAN, DAY) == dict(expected, expires_at="2032-05-05T00:00:00Z")
    derived = [rows for pack_name, rel, rows in reads if (pack_name, rel) == ("provider-terms", "order_guarantee")]
    assert derived, reads
    assert {(mode, expires) for _, mode, expires in derived[-1]} == {
        ("binding_quote", str(utc_us(2032, 5, 5, 0, 0)))
    }

    # Usage-billed detail types are refused via provider-terms, even at zero price.
    for kind in ("CONSUMPTION", "OUTPLAN"):
        body = order()
        body["details"].append(dict(deepcopy(body["details"][1]), detailType=kind, totalPrice=price(0)))
        reads.clear()
        with pytest.raises(ValueError, match="usage"):
            guarantee(body, record(), PLAN, DAY)
        derived = [rows for pack_name, rel, rows in reads if (pack_name, rel) == ("provider-terms", "order_guarantee")]
        assert derived and derived[-1] == set(), derived
