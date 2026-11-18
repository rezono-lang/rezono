"""Compare an expected offer with injected price and stock observations."""

from collections.abc import Callable
from typing import TypedDict


class OfferInspection(TypedDict):
    sku: str
    expected_price: int
    observed_price: int | None
    required_stock: int
    observed_stock: int | None
    findings: list[str]


def _read(reader: Callable[[str], int | None], sku: str) -> int | None:
    try:
        return reader(sku)
    except OSError:
        return None


def inspect_offer(
    sku: str,
    expected_price: int,
    required_stock: int,
    read_price: Callable[[str], int | None],
    read_stock: Callable[[str], int | None],
) -> OfferInspection:
    """Read each observation once and report price drift and stock independently."""
    if not isinstance(sku, str) or not sku:
        raise ValueError("SKU must be a nonempty string")
    for label, value in (("expected price", expected_price), ("required stock", required_stock)):
        if type(value) is not int or value < 0:
            raise ValueError(f"{label} must be a nonnegative integer")

    observed_price = _read(read_price, sku)
    observed_stock = _read(read_stock, sku)
    for label, value in (("observed price", observed_price), ("observed stock", observed_stock)):
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError(f"{label} must be a nonnegative integer or unknown")

    findings = []
    if observed_price is None:
        findings.append("price_unknown")
    elif observed_price != expected_price:
        findings.append("price_changed")
    if observed_stock is None:
        findings.append("stock_unknown")
    elif observed_stock < required_stock:
        findings.append("insufficient_stock")
    return {
        "sku": sku,
        "expected_price": expected_price,
        "observed_price": observed_price,
        "required_stock": required_stock,
        "observed_stock": observed_stock,
        "findings": findings,
    }
