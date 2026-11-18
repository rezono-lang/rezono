"""Resolve one recorded order attempt through its durable claim and status port."""

from collections.abc import Callable, Mapping
import re
from typing import Literal

Receipt = Mapping[str, object]
Operation = Callable[[str], Receipt | None]


def _matching_receipt(receipt: Receipt | None, plan_hash: str) -> Receipt | None:
    if isinstance(receipt, Mapping) and receipt.get("plan_hash") == plan_hash:
        order_id = receipt.get("id")
        if isinstance(order_id, str) and order_id.strip():
            return receipt
    return None


def invoke(
    plan_hash: str, claim: Callable[[str], bool], apply: Operation, status: Operation
) -> tuple[Literal["applied", "unknown"], Receipt | None]:
    """Dispatch only on a new claim, otherwise resolve the same key by status."""
    if not isinstance(plan_hash, str) or re.fullmatch(r"[0-9a-f]{64}", plan_hash) is None:
        raise ValueError("the plan hash must contain 64 lowercase hexadecimal characters")

    if claim(plan_hash):
        try:
            receipt = _matching_receipt(apply(plan_hash), plan_hash)
        except TimeoutError:
            receipt = None
        if receipt is not None:
            return "applied", receipt

    try:
        receipt = _matching_receipt(status(plan_hash), plan_hash)
    except TimeoutError:
        receipt = None
    return ("unknown", None) if receipt is None else ("applied", receipt)
