"""Extract exact hourly prices from a verified local capture."""

from decimal import Decimal
from hashlib import sha256
import json


def hourly_micros(raw: bytes, digest: str) -> dict[str, int]:
    """Return hourly prices by SKU in whole millionths, without rounding."""
    if sha256(raw).hexdigest() != digest:
        raise ValueError("price capture bytes do not match the SHA-256 digest")

    document = json.loads(raw.decode("utf-8"), parse_int=Decimal, parse_float=Decimal)
    rows = document.get("plans_metal") if isinstance(document, dict) else None
    if not isinstance(rows, list):
        raise ValueError("price capture requires a plans_metal list")

    prices: dict[str, int] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each price row must be an object")
        sku = row.get("id")
        if not isinstance(sku, str) or not sku.strip() or sku in prices:
            raise ValueError("each price row needs a unique nonempty SKU")
        price = row.get("hourly_cost")
        if not isinstance(price, Decimal) or not price.is_finite() or price < 0:
            raise ValueError("hourly cost must be a nonnegative decimal")
        numerator, denominator = price.as_integer_ratio()
        micros, remainder = divmod(numerator * 1_000_000, denominator)
        if remainder:
            raise ValueError("hourly cost has precision finer than one millionth")
        prices[sku] = micros
    return prices
