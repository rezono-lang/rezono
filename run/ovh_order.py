"""Read an unpaid OVHcloud order into a binding quote guarantee, per decisions/run-price-enforcement.md."""

from collections.abc import Mapping
from datetime import date, datetime, time, timedelta, timezone
from fractions import Fraction
import re

_UCENTS_PER_UNIT = 10**8
_PLAN_HASH_RE = re.compile(r"[0-9a-f]{64}")
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_USAGE_DETAIL_TYPES = frozenset({"CONSUMPTION", "OUTPLAN"})


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
    for index, detail in enumerate(details):
        if not isinstance(detail, Mapping):
            raise ValueError("each order detail must be an object")
        detail_type = detail.get("detailType")
        if not isinstance(detail_type, str) or not detail_type.strip():
            raise ValueError("order detail requires a nonempty detailType")
        if detail_type in _USAGE_DETAIL_TYPES:
            raise ValueError("usage-billed order detail gives no guarantee")
        detail_currency, line_ucents = _price(detail.get("totalPrice"), f"details[{index}].totalPrice")
        if detail_currency != currency:
            raise ValueError("currency mismatch across order details")
        details_total += line_ucents

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
    expires = min(expiration_utc, day_end)

    total = Fraction(with_tax, _UCENTS_PER_UNIT)
    return {
        "mode": "binding_quote",
        "currency": currency,
        "total": [total.numerator, total.denominator],
        "includes_setup": True,
        "expires_at": expires.isoformat().replace("+00:00", "Z"),
        "reference": str(order_id),
        "plan_hash": plan_hash,
    }
