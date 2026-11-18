"""Enforce the round budget after each reconciliation observation."""

from collections.abc import Iterable


def can_continue(used: int, limit: int, pending: Iterable[str]) -> bool:
    """Return whether another round is needed and permitted."""
    if type(limit) is not int or limit <= 0:
        raise ValueError("round limit must be a positive integer")
    if type(used) is not int or used < 0:
        raise ValueError("used rounds must be a nonnegative integer")

    pending_steps = sorted(set(pending))
    if not pending_steps:
        return False
    if used >= limit:
        raise ValueError(f"round limit reached with pending steps: {', '.join(pending_steps)}")
    return True
