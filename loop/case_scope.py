"""Resolve a declared case against the closed synthetic fixture inventory."""

from collections.abc import Iterable, Set


def resolve_case(
    case_id: str, cases: Iterable[dict[str, object]], inventory: Set[str]
) -> dict[str, object]:
    """Return the single declared case with its exact endpoint tuple."""
    matches = [case for case in cases if case.get("id") == case_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one declared fixture case for {case_id!r}")

    case = matches[0]
    for key in ("source", "destination"):
        endpoint = case.get(key)
        if not isinstance(endpoint, str) or not endpoint or endpoint not in inventory:
            raise ValueError(f"fixture case {case_id!r} has an undeclared {key}")
    protocol, port = case.get("protocol"), case.get("port")
    if not isinstance(protocol, str) or not protocol or protocol.strip() != protocol:
        raise ValueError(f"fixture case {case_id!r} has an invalid protocol")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError(f"fixture case {case_id!r} has an invalid port")
    return case
