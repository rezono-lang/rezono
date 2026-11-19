"""Count the planner queue from a complete pull listing."""

from collections.abc import Iterable, Mapping
from typing import Any


def queue_reading(
    pulls: Iterable[Mapping[str, Any]],
    *,
    run: str,
    observed_at: int,
    source: str,
    complete: bool,
    base: str,
) -> dict[str, Any] | None:
    """Return one queue reading, or None when the listing is incomplete.

    The queue is the open pull requests against ``base`` that are not drafts.
    """
    if not complete:
        return None
    seen: set[int] = set()
    count = 0
    for pull in pulls:
        number = pull["number"]
        if number in seen:
            raise ValueError(f"pull request {number} listed twice")
        seen.add(number)
        if pull["state"] == "open" and not pull["draft"] and pull["base"]["ref"] == base:
            count += 1
    return {"id": f"queue@{observed_at}", "run": run, "observed_at": observed_at, "count": count, "source": source}
