"""Order the explicitly registered cases of a synthetic fixture."""

from collections.abc import Iterable, Mapping


def schedule(cases: Iterable[Mapping[str, object]]) -> list[tuple[str, str, str, str, int]]:
    """Return each declared case once, ordered by its unique identifier."""
    scheduled = []
    seen: set[str] = set()
    for case in cases:
        case_id, source, destination, protocol = (
            case.get(key) for key in ("id", "source", "destination", "protocol")
        )
        if not isinstance(case_id, str) or not case_id or case_id in seen:
            raise ValueError(f"invalid or duplicate fixture case ID: {case_id!r}")
        if not isinstance(source, str) or not source or not isinstance(destination, str) or not destination:
            raise ValueError(f"fixture case {case_id!r} requires explicit endpoints")
        port = case.get("port")
        if not isinstance(protocol, str) or not protocol or type(port) is not int or not 1 <= port <= 65535:
            raise ValueError(f"fixture case {case_id!r} requires an explicit protocol and numeric port")
        seen.add(case_id)
        scheduled.append((case_id, source, destination, protocol, port))
    return sorted(scheduled)
