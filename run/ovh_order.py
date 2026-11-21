"""Read an unpaid OVHcloud order into a quote guarantee using the provider-terms pack, per decisions/run-price-enforcement.md."""

from collections.abc import Mapping
from contextlib import closing
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
from functools import cache
from pathlib import Path
import re

from rezono_compiler import batch, facts, pack, rules, scenarios

_UCENTS_PER_UNIT = 10**8
_PLAN_HASH_RE = re.compile(r"[0-9a-f]{64}")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_MICROSECOND = timedelta(microseconds=1)
_PACK_DIR = Path(__file__).resolve().parent / "packs" / "provider-terms"


@cache
def _provider_terms() -> tuple[pack.Pack, rules.Program, dict[str, list[tuple]]]:
    model = pack.read(_PACK_DIR)
    program = rules.load(model.rules)
    states = scenarios.fact_states(model, _PACK_DIR, diagnostics=False)
    if not states:
        raise ValueError("provider-terms pack must provide fact states")
    return model, program, states[0][3]


def _price(value: object, label: str) -> tuple[str, int]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    currency = value.get("currencyCode")
    if not isinstance(currency, str) or not currency.strip():
        raise ValueError(f"{label} requires a nonempty currencyCode")
    ucents = value.get("priceInUcents")
    if type(ucents) is not int or ucents < 0:
        raise ValueError(f"{label} priceInUcents must be a nonnegative integer")
    return currency, ucents


def _positive_order_id(mapping: Mapping[str, object], label: str) -> int:
    order_id = mapping.get("orderId")
    if type(order_id) is not int or order_id <= 0:
        raise ValueError(f"{label} requires a positive integer order id")
    return order_id


def _utc_timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"record requires an {label} string")
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"record {label} must be an ISO-8601 timestamp") from exc
    if instant.utcoffset() is None:
        raise ValueError(f"record {label} requires a UTC offset")
    return instant.astimezone(timezone.utc)


def _approved_day(day: object) -> date:
    if not isinstance(day, str) or _DAY_RE.fullmatch(day) is None:
        raise ValueError("day must be a YYYY-MM-DD date")
    try:
        return date.fromisoformat(day)
    except ValueError as exc:
        raise ValueError("day must be a valid calendar date") from exc


def guarantee(
    order: Mapping[str, object],
    record: Mapping[str, object],
    plan_hash: str,
    day: str,
) -> dict[str, object]:
    """Validate an unpaid OVHcloud order and its record and return the binding quote guarantee."""
    if not isinstance(plan_hash, str) or _PLAN_HASH_RE.fullmatch(plan_hash) is None:
        raise ValueError("plan hash must be 64 lowercase hexadecimal characters")
    order_day = _approved_day(day)
    if not isinstance(order, Mapping):
        raise ValueError("order must be an object")
    if not isinstance(record, Mapping):
        raise ValueError("record must be an object")

    order_id = _positive_order_id(order, "order")
    record_order_id = _positive_order_id(record, "record")
    if record_order_id != order_id:
        raise ValueError("record order id does not match order")

    details = order.get("details")
    if not isinstance(details, list) or not details:
        raise ValueError("order details must be a nonempty list")

    prices = order.get("prices")
    if not isinstance(prices, Mapping):
        raise ValueError("order requires a prices object")

    currency, with_tax = _price(prices.get("withTax"), "prices.withTax")
    without_currency, without_tax = _price(prices.get("withoutTax"), "prices.withoutTax")
    tax_currency, tax = _price(prices.get("tax"), "prices.tax")
    if without_currency != currency or tax_currency != currency:
        raise ValueError("currency mismatch across order prices")

    details_total = 0
    detail_types: list[str] = []
    for index, detail in enumerate(details):
        if not isinstance(detail, Mapping):
            raise ValueError("each order detail must be an object")
        detail_type = detail.get("detailType")
        if not isinstance(detail_type, str) or not detail_type.strip():
            raise ValueError("order detail requires a nonempty detailType")
        detail_currency, line_ucents = _price(detail.get("totalPrice"), f"details[{index}].totalPrice")
        if detail_currency != currency:
            raise ValueError("currency mismatch across order details")
        details_total += line_ucents
        detail_types.append(detail_type)

    if details_total != without_tax:
        raise ValueError("order details totalPrice sum does not match prices.withoutTax")
    if without_tax + tax != with_tax:
        raise ValueError("order prices.withoutTax plus prices.tax does not equal prices.withTax")

    record_currency, record_with_tax = _price(record.get("priceWithTax"), "record priceWithTax")
    if record_currency != currency:
        raise ValueError("record priceWithTax currency does not match order currency")
    if record_with_tax != with_tax:
        raise ValueError("record priceWithTax does not match order prices.withTax")

    expiration_utc = _utc_timestamp(record.get("expirationDate"), "expirationDate")
    day_end = datetime.combine(order_day + timedelta(days=1), time.min, timezone.utc)

    model, program, pack_facts = _provider_terms()
    order_key = str(order_id)
    runtime_rows = facts.rows_of(model, {
        "order": [{
            "id": order_key,
            "expiration_us": (expiration_utc - _EPOCH) // _MICROSECOND,
            "day_end_us": (day_end - _EPOCH) // _MICROSECOND,
        }],
        "order_detail": [
            {"id": f"{order_key}/{index}", "order": order_key, "detail_type": detail_type}
            for index, detail_type in enumerate(detail_types)
        ],
    })
    merged = {
        table: [*pack_facts.get(table, ()), *runtime_rows.get(table, ())]
        for table in pack_facts.keys() | runtime_rows.keys()
    }
    inputs = scenarios.rule_rows(model, program, merged)
    with closing(batch.connect(program, inputs)) as connection:
        batch.compute(connection, program)
        derived = batch.read(connection, program, ["order_guarantee", "no_guarantee"])
    guarantees = derived["order_guarantee"]
    refusals = derived["no_guarantee"]
    if refusals:
        reasons = sorted({reason for order_ref, reason in refusals if order_ref == order_key})
        if reasons:
            raise ValueError(f"provider terms gave no guarantee: {', '.join(reasons)}")
        raise ValueError("provider terms gave no guarantee")
    if not guarantees:
        raise ValueError("provider terms gave no guarantee")
    if len(guarantees) != 1:
        raise ValueError("provider terms derived ambiguous order guarantee")
    (_, mode, expires_us_text), = guarantees
    expires = _EPOCH + timedelta(microseconds=int(expires_us_text))

    total = Fraction(with_tax, _UCENTS_PER_UNIT)
    return {
        "mode": mode,
        "currency": currency,
        "total": [total.numerator, total.denominator],
        "includes_setup": True,
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "reference": order_key,
        "plan_hash": plan_hash,
    }
