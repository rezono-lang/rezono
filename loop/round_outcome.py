"""Classify a reconciliation round after evaluating its observations."""

from collections.abc import Collection
from typing import Literal


def outcome(
    *,
    declared: Collection[str],
    done: Collection[str],
    stuck: Collection[str],
    drift: Collection[object],
) -> Literal["success", "pending", "failure"]:
    """Give blockers and terminal drift precedence over clean completion."""
    if stuck or drift:
        return "failure"
    if set(declared).issubset(done):
        return "success"
    return "pending"
