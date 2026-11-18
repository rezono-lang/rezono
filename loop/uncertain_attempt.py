"""Select the reconciliation operation for a recorded nonrepeatable attempt."""

from collections.abc import Mapping
import re
from typing import Literal


def next_operation(plan_hash: str, attempt: Mapping[str, str]) -> Literal["status"] | None:
    """Request status for an uncertain attempt attached to the exact plan."""
    if not isinstance(plan_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", plan_hash):
        raise ValueError("expected a lowercase SHA-256 plan digest")
    if attempt.get("idempotency_key") != plan_hash:
        raise ValueError("attempt idempotency key must match the plan digest")

    state = attempt.get("state")
    if state in ("applying", "unknown"):
        return "status"
    if state in ("planned", "applied", "failed", "cleaned"):
        return None
    raise ValueError("invalid recorded attempt state")
