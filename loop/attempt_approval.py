"""Determine whether a nonrepeatable effect is eligible for a durable claim."""

import re


def claimable(*, plan_hash: str, approved_hash: str | None, state: str) -> bool:
    """Only a planned effect with approval of its full digest may be claimed."""
    return (
        state == "planned"
        and isinstance(plan_hash, str)
        and re.fullmatch(r"[0-9a-f]{64}", plan_hash) is not None
        and approved_hash == plan_hash
    )
