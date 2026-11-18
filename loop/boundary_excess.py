"""Identify excess router allowances from recorded layer verdicts."""

from collections.abc import Iterable
from typing import Literal, TypedDict


class BoundaryCase(TypedDict):
    id: str
    router: Literal["allow", "deny", "inapplicable"]
    service: Literal["allow", "deny"]


def excess(cases: Iterable[BoundaryCase]) -> set[str]:
    """Return the case IDs allowed at the router and denied by service isolation."""
    return {case["id"] for case in cases if case["router"] == "allow" and case["service"] == "deny"}
