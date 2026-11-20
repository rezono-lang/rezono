"""Create an unpaid OVHcloud order through a provider port, per decisions/run-price-enforcement.md."""

from collections.abc import Callable, Mapping
from datetime import datetime
import re

_HASH = re.compile(r"[0-9a-f]{64}")

ProviderCall = Callable[[str, str, dict[str, object] | None], object]


def _nonempty_str(mapping: Mapping[str, object], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a nonempty string")
    return value


def _expire_timestamp(request: Mapping[str, object]) -> str:
    expire = _nonempty_str(request, "expire")
    try:
        instant = datetime.fromisoformat(expire)
    except ValueError as exc:
        raise ValueError("expire must be an ISO-8601 timestamp with timezone") from exc
    if instant.utcoffset() is None:
        raise ValueError("expire must include a UTC offset")
    return expire


def _configuration(request: Mapping[str, object]) -> list[tuple[str, str]]:
    config = request.get("configuration")
    if not isinstance(config, Mapping):
        raise ValueError("configuration must be a mapping")
    entries: list[tuple[str, str]] = []
    for label, value in sorted(config.items()):
        if not isinstance(label, str) or not label.strip():
            raise ValueError("configuration label must be a nonempty string")
        if not isinstance(value, str) or not value.strip():
            raise ValueError("configuration value must be a nonempty string")
        entries.append((label, value))
    return entries


def _with_tax(payload: object, source: str) -> tuple[str, int]:
    if not isinstance(payload, Mapping):
        raise ValueError(f"{source} must be an object")
    prices = payload.get("prices")
    if not isinstance(prices, Mapping):
        raise ValueError(f"{source} requires prices")
    with_tax = prices.get("withTax")
    if not isinstance(with_tax, Mapping):
        raise ValueError(f"{source} requires prices.withTax")
    currency = _nonempty_str(with_tax, "currencyCode")
    ucents = with_tax.get("priceInUcents")
    if type(ucents) is not int or ucents < 0:
        raise ValueError(f"{source} prices.withTax.priceInUcents must be a nonnegative integer")
    return currency, ucents


def _validated_request(
    request: Mapping[str, object],
) -> tuple[str, str, str, str, int, list[tuple[str, str]], str, str, bool]:
    if not isinstance(request, Mapping):
        raise ValueError("request must be a mapping")
    subsidiary = _nonempty_str(request, "subsidiary")
    plan_code = _nonempty_str(request, "plan_code")
    duration = _nonempty_str(request, "duration")
    pricing_mode = _nonempty_str(request, "pricing_mode")
    quantity = request.get("quantity")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("quantity must be a positive integer")
    configuration = _configuration(request)
    plan_hash = request.get("plan_hash")
    if not isinstance(plan_hash, str) or _HASH.fullmatch(plan_hash) is None:
        raise ValueError("plan_hash must be 64 lowercase hexadecimal characters")
    expire = _expire_timestamp(request)
    waive_retraction = request.get("waive_retraction")
    if type(waive_retraction) is not bool:
        raise ValueError("waive_retraction must be a boolean")
    return (
        subsidiary,
        plan_code,
        duration,
        pricing_mode,
        quantity,
        configuration,
        plan_hash,
        expire,
        waive_retraction,
    )


def checkout(call: ProviderCall, request: Mapping[str, object]) -> dict[str, object]:
    """Create a cart, configure one item, check its preview total, and place an unpaid order."""
    if not callable(call):
        raise ValueError("call must be callable")
    (
        subsidiary,
        plan_code,
        duration,
        pricing_mode,
        quantity,
        configuration,
        plan_hash,
        expire,
        waive_retraction,
    ) = _validated_request(request)

    cart = call(
        "POST",
        "/order/cart",
        {"ovhSubsidiary": subsidiary, "description": plan_hash, "expire": expire},
    )
    if not isinstance(cart, Mapping):
        raise ValueError("cart response must be an object")
    cart_id = _nonempty_str(cart, "cartId")
    if "/" in cart_id or any(ch.isspace() for ch in cart_id):
        raise ValueError("cartId must not contain slashes or whitespace")

    call("POST", f"/order/cart/{cart_id}/assign", None)
    item = call(
        "POST",
        f"/order/cart/{cart_id}/baremetalServers",
        {
            "planCode": plan_code,
            "duration": duration,
            "pricingMode": pricing_mode,
            "quantity": quantity,
        },
    )
    if not isinstance(item, Mapping):
        raise ValueError("cart item response must be an object")
    if "cartId" in item and item["cartId"] != cart_id:
        raise ValueError("cart item cartId does not match the created cart")
    item_id = item.get("itemId")
    if type(item_id) is not int or item_id < 0:
        raise ValueError("itemId must be a nonnegative integer")

    for label, value in configuration:
        call(
            "POST",
            f"/order/cart/{cart_id}/item/{item_id}/configuration",
            {"label": label, "value": value},
        )

    preview = call("GET", f"/order/cart/{cart_id}/checkout", None)
    preview_total = _with_tax(preview, "checkout read")

    order = call(
        "POST",
        f"/order/cart/{cart_id}/checkout",
        {
            "autoPayWithPreferredPaymentMethod": False,
            "waiveRetractationPeriod": waive_retraction,
        },
    )
    order_total = _with_tax(order, "created order")
    if order_total != preview_total:
        raise ValueError("created order total differs from checkout read")
    if not isinstance(order, Mapping) or type(order.get("orderId")) is not int or order["orderId"] <= 0:
        raise ValueError("created order requires a positive integer orderId")
    return dict(order)
