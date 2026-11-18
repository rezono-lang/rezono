"""Logical keys for delivery step statuses on proposal commits."""

import re


def context(commit: str, tenant: str, delivery: str, step: str) -> tuple[str, str]:
    """Return the pinned commit and the delivery step's stable status context."""
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("commit must be a full Git commit object ID")

    for field, segment in (("tenant", tenant), ("delivery", delivery), ("step", step)):
        if not isinstance(segment, str) or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", segment):
            raise ValueError(f"{field} must be a lowercase ASCII slug")

    return commit, f"rezono/delivery/{tenant}/{delivery}/{step}"
