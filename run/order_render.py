"""Project approved plan bytes to an offline order payload."""

import hashlib
import json
from typing import TypedDict


class OrderItem(TypedDict):
    sku: str
    quantity: int
    plan_hash: str


class OrderPayload(TypedDict):
    idempotency_key: str
    items: list[OrderItem]


def _object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate plan field {key!r}")
        result[key] = value
    return result


def render(raw: bytes, plan_hash: str) -> OrderPayload:
    """Check the byte digest before projecting the ordered SKU and quantity lines."""
    digest = hashlib.sha256(raw).hexdigest()
    if digest != plan_hash:
        raise ValueError("plan hash does not match the supplied bytes")
    plan = json.loads(raw.decode("utf-8"), object_pairs_hook=_object)
    lines = plan.get("lines") if isinstance(plan, dict) else None
    if not isinstance(lines, list):
        raise ValueError("plan must contain a list of order lines")

    items: list[OrderItem] = []
    for line in lines:
        if not isinstance(line, dict):
            raise ValueError("each order line must be an object")
        sku, quantity = line.get("sku"), line.get("quantity")
        if not isinstance(sku, str) or not sku or type(quantity) is not int or quantity < 0:
            raise ValueError("order line requires a nonempty SKU and a nonnegative integer quantity")
        items.append({"sku": sku, "quantity": quantity, "plan_hash": digest})
    return {"idempotency_key": digest, "items": items}
