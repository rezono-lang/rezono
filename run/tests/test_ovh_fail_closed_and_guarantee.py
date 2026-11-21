"""OVH order/renewal/status and exact-quote readers fail closed on missing pack facts, and
provider-terms derives no_guarantee(order, reason): decisions/code-does-not-decide.md
(see also decisions/run-price-enforcement.md).
"""

from __future__ import annotations

import ast
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from runpy import run_path

import pytest

from offline_cases import RUN

EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
PLAN = "a" * 64
DAY = "2032-05-04"
DEADLINE = "2032-05-04T22:00:00Z"
PROVIDER_TERMS = RUN / "packs" / "provider-terms"


def _utc_us(year: int, month: int, day: int, hour: int = 0, minute: int = 0) -> int:
    return (datetime(year, month, day, hour, minute, tzinfo=timezone.utc) - EPOCH) // timedelta(microseconds=1)


def _price(ucents: int) -> dict[str, object]:
    return {
        "currencyCode": "EUR",
        "priceInUcents": ucents,
        "value": ucents / 10**8,
        "text": f"{ucents} uc",
    }


def _order() -> dict[str, object]:
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
                "unitPrice": _price(4999000000),
                "totalPrice": _price(4999000000),
            },
            {
                "cartItemID": 1,
                "description": "first month",
                "detailType": "DURATION",
                "domain": "*",
                "quantity": 1,
                "unitPrice": _price(8999000000),
                "totalPrice": _price(8999000000),
            },
        ],
        "prices": {
            "withoutTax": _price(13998000000),
            "tax": _price(2799600000),
            "withTax": _price(16797600000),
        },
    }


def _record() -> dict[str, object]:
    return {
        "orderId": 4711,
        "date": "2032-05-04T09:00:00+02:00",
        "expirationDate": "2032-05-05T01:30:00+02:00",
        "priceWithTax": _price(16797600000),
    }


def _auto_renewing_service() -> dict[str, object]:
    return {
        "serviceId": 9,
        "domain": "srv-1.example.org",
        "status": "ok",
        "creation": "2032-05-04",
        "expiration": "2032-06-03",
        "engagedUpTo": None,
        "renewalType": "automatic",
        "renew": {
            "automatic": True,
            "forced": True,
            "deleteAtExpiration": False,
            "manualPayment": False,
            "period": 1,
        },
    }


def _string_literals(path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    }


def _eval_provider_terms(runtime_data: dict[str, list[dict[str, object]]]) -> dict[str, set[tuple[str, ...]]]:
    from rezono_compiler import batch, facts, pack, rules, scenarios

    model = pack.read(PROVIDER_TERMS)
    program = rules.load(model.rules)
    states = scenarios.fact_states(model, PROVIDER_TERMS, diagnostics=False)
    assert states, "provider-terms must provide pack facts"
    pack_facts = states[0][3]
    runtime_rows = facts.rows_of(model, runtime_data)
    merged = {
        table: [*pack_facts.get(table, ()), *runtime_rows.get(table, ())]
        for table in pack_facts.keys() | runtime_rows.keys()
    }
    inputs = scenarios.rule_rows(model, program, merged)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        out = batch.read(connection, program, ["order_guarantee", "no_guarantee"])
    return {name: set(rows) for name, rows in out.items()}


def test_ovh_modules_fail_closed_on_empty_fact_states(monkeypatch):
    from rezono_compiler import batch, scenarios

    monkeypatch.setattr(scenarios, "fact_states", lambda *args, **kwargs: [])
    connect_calls: list[str] = []
    real_connect = batch.connect

    def spy_connect(program, *args, **kwargs):
        connect_calls.append(program.pack)
        return real_connect(program, *args, **kwargs)

    monkeypatch.setattr(batch, "connect", spy_connect)

    # 1. ovh_renewal: empty fact_states must raise explicitly, never return [] on an auto-renewing service.
    renewal = run_path(str(RUN / "ovh_renewal.py"))
    connect_calls.clear()
    with pytest.raises((ValueError, RuntimeError)):
        renewal["blocks"](_auto_renewing_service(), DEADLINE)
    assert connect_calls == [], "ovh_renewal must fail closed before running rules with empty pack facts"

    # 2. ovh_order_status: empty fact_states must raise explicitly, never silently return 'unresolved'.
    order_status = run_path(str(RUN / "ovh_order_status.py"))
    connect_calls.clear()
    with pytest.raises((ValueError, RuntimeError)):
        order_status["outcome"](b'"delivered"')
    assert connect_calls == [], "ovh_order_status must fail closed before running rules with empty pack facts"

    # 3. ovh_order: empty fact_states must raise explicitly, never fall back to {} and blame usage-billed details.
    ovh_order = run_path(str(RUN / "ovh_order.py"))
    connect_calls.clear()
    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        ovh_order["guarantee"](_order(), _record(), PLAN, DAY)
    assert "usage" not in str(exc_info.value).lower(), (
        f"ovh_order fell back to {{}} and blamed usage billing instead of missing fact states: {exc_info.value}"
    )
    assert connect_calls == [], "ovh_order must fail closed before running rules with empty pack facts"


def test_effective_quote_fails_closed_on_empty_fact_states(monkeypatch):
    from rezono_compiler import scenarios

    monkeypatch.setattr(scenarios, "fact_states", lambda *args, **kwargs: [])
    effective_quote = run_path(str(RUN / "effective_quote.py"))

    with pytest.raises((ValueError, RuntimeError)) as exc_info:
        effective_quote["pack_currencies"]()
    msg = str(exc_info.value).lower()
    assert "quote currency" not in msg, (
        f"effective_quote fell back to {{}} instead of failing closed on empty fact states: {exc_info.value}"
    )


def test_order_no_guarantee_reason_comes_from_provider_terms(monkeypatch):
    from rezono_compiler import batch, pack, rules

    model = pack.read(PROVIDER_TERMS)
    program = rules.load(model.rules)
    assert "no_guarantee" in set(program.derived()), (
        "run/packs/provider-terms must derive no_guarantee(order, reason)"
    )
    assert len(program.relations["no_guarantee"].key) == 2, (
        "no_guarantee must have 2 key columns: (order, reason)"
    )

    exp_us = _utc_us(2032, 5, 4, 23, 30)
    day_end_us = _utc_us(2032, 5, 5, 0, 0)

    # Valid order: guarantee holds, no_guarantee is empty.
    valid_out = _eval_provider_terms({
        "order": [{"id": "4711", "expiration_us": exp_us, "day_end_us": day_end_us}],
        "order_detail": [
            {"id": "4711/0", "order": "4711", "detail_type": "INSTALLATION"},
            {"id": "4711/1", "order": "4711", "detail_type": "DURATION"},
        ],
    })
    assert len(valid_out["order_guarantee"]) == 1
    assert valid_out["no_guarantee"] == set()

    # Usage-billed detail types derive a usage-identifying no_guarantee reason.
    usage_reasons: set[str] = set()
    for detail_type in ("CONSUMPTION", "OUTPLAN"):
        usage_out = _eval_provider_terms({
            "order": [{"id": "4711", "expiration_us": exp_us, "day_end_us": day_end_us}],
            "order_detail": [
                {"id": "4711/0", "order": "4711", "detail_type": "INSTALLATION"},
                {"id": "4711/1", "order": "4711", "detail_type": detail_type},
            ],
        })
        assert usage_out["order_guarantee"] == set()
        assert len(usage_out["no_guarantee"]) == 1, usage_out["no_guarantee"]
        (order_id, reason), = usage_out["no_guarantee"]
        assert order_id == "4711"
        assert "usage" in reason.lower(), f"expected usage reason for {detail_type}, got {reason!r}"
        usage_reasons.add(reason)

    # Non-usage invalid order (missing details) derives a distinct non-usage no_guarantee reason.
    invalid_out = _eval_provider_terms({
        "order": [{"id": "4712", "expiration_us": exp_us, "day_end_us": day_end_us}],
        "order_detail": [],
    })
    assert invalid_out["order_guarantee"] == set()
    assert invalid_out["no_guarantee"], "invalid order with no details must derive a no_guarantee reason"
    for order_id, reason in invalid_out["no_guarantee"]:
        assert order_id == "4712"
        assert "usage" not in reason.lower(), (
            f"non-usage invalid order must not get a usage reason, got {reason!r}"
        )

    # run/ovh_order.py must not hardcode 'usage-billed' in Python.
    code_literals = _string_literals(RUN / "ovh_order.py")
    assert not any("usage" in lit.lower() for lit in code_literals), (
        f"run/ovh_order.py must not invent usage-billed reason text in Python: {sorted(code_literals)}"
    )

    # run/ovh_order.py must read no_guarantee from provider-terms and report its derived reason.
    reads: list[tuple[str, str, set[tuple[str, ...]]]] = []
    real_read = batch.read

    def spy_read(con, prog, names=None):
        result = real_read(con, prog, names)
        for name, values in result.items():
            reads.append((prog.pack, name, set(values)))
        return result

    monkeypatch.setattr(batch, "read", spy_read)
    ovh_order = run_path(str(RUN / "ovh_order.py"))

    usage_order = _order()
    usage_order["details"].append(
        dict(deepcopy(usage_order["details"][1]), detailType="CONSUMPTION", totalPrice=_price(0))
    )
    with pytest.raises(ValueError) as exc_info:
        ovh_order["guarantee"](usage_order, _record(), PLAN, DAY)

    no_guarantee_reads = [
        rows for pack_name, rel, rows in reads if (pack_name, rel) == ("provider-terms", "no_guarantee")
    ]
    assert no_guarantee_reads, f"run/ovh_order.py did not read provider-terms.no_guarantee; saw {reads}"
    derived_reasons = {reason for _, reason in no_guarantee_reads[-1]}
    assert derived_reasons <= usage_reasons and derived_reasons
    assert any(reason in str(exc_info.value) for reason in derived_reasons), (
        f"ValueError {str(exc_info.value)!r} did not include derived no_guarantee reason {derived_reasons}"
    )

    # Substituting a distinct pack-derived reason proves Python renders no_guarantee output verbatim.
    def custom_read(con, prog, names=None):
        result = real_read(con, prog, names)
        out = dict(result)
        if "order_guarantee" in out:
            out["order_guarantee"] = []
        if "no_guarantee" in out:
            out["no_guarantee"] = [("4711", "policy_conflict_test_reason")]
        return out

    monkeypatch.setattr(batch, "read", custom_read)
    with pytest.raises(ValueError) as custom_exc:
        ovh_order["guarantee"](_order(), _record(), PLAN, DAY)
    assert "policy_conflict_test_reason" in str(custom_exc.value), (
        f"expected pack-derived reason in ValueError, got: {custom_exc.value}"
    )
