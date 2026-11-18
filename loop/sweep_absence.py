"""Derive absence evidence from a completed observation sweep."""

from collections.abc import Mapping


def absence(
    run: str, sweep: str, complete: bool, desired: Mapping[str, str], present: Mapping[str, str]
) -> list[tuple[str, str, str, str]]:
    """Return (run, object, desired reference, sweep) for missing objects in this scope."""
    if not complete:
        return []
    return [(run, key, desired[key], sweep) for key in sorted(desired.keys() - present.keys())]
