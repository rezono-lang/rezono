"""Project delivery timing from observations of the current step and run."""

from collections.abc import Iterable, Mapping
from datetime import datetime


def times(
    scope: Mapping[str, str], evidence: Iterable[Mapping[str, str]]
) -> tuple[int | None, str | None]:
    """Return elapsed waiting seconds and the recorded completion timestamp."""
    identity = {key: scope[key] for key in ("run", "tenant", "delivery", "step")}
    events: dict[str, list[tuple[datetime, str]]] = {"waiting": [], "sweep": [], "done": []}
    for row in evidence:
        state = row.get("state")
        if state not in events or any(row.get(key) != value for key, value in identity.items()):
            continue
        timestamp = row["at"]
        if not timestamp.endswith("Z"):
            raise ValueError("observation time must be a UTC timestamp ending in Z")
        events[state].append((datetime.fromisoformat(timestamp), timestamp))

    completion = min(events["done"], default=None)
    end = completion or max(events["sweep"], default=None)
    elapsed = None
    if end is not None:
        entered = max((at for at, _ in events["waiting"] if at <= end[0]), default=None)
        if entered is not None:
            delta = end[0] - entered
            elapsed = delta.days * 86400 + delta.seconds

    return elapsed, completion[1] if completion is not None else None
