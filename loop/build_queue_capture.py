"""Count the planner queue from a complete pull listing."""

from collections.abc import Iterable, Mapping
from typing import Any


def _receipt_for(receipt: Mapping[str, Any] | None, run: str, observed_at: int) -> str | None:
    """Return the receipt ID when it attests a complete read of this run at this cut."""
    if not isinstance(receipt, Mapping):
        return None
    name = receipt.get("id")
    if not isinstance(name, str) or not name.strip() or receipt.get("run") != run:
        return None
    tick = receipt.get("event_time")
    return name if type(tick) is int and tick == observed_at else None


def _fields(pull: object) -> tuple[int, str, bool, str] | None:
    """Return number, state, draft flag and base branch, or None when any of them is unreadable."""
    if not isinstance(pull, Mapping):
        return None
    number, state, draft, base = (pull.get(key) for key in ("number", "state", "draft", "base"))
    if type(number) is not int or not isinstance(state, str) or type(draft) is not bool:
        return None
    if not isinstance(base, Mapping) or not isinstance(base.get("ref"), str):
        return None
    return number, state, draft, base["ref"]


def queue_reading(
    pulls: Iterable[Mapping[str, Any]],
    *,
    run: str,
    observed_at: int,
    source: str,
    receipt: Mapping[str, Any] | None,
    base: str,
) -> dict[str, Any] | None:
    """Return one queue reading, or None when completeness or a counted field is unknown.

    The queue is the open pull requests against ``base`` that are not drafts. ``receipt`` is the
    ``LoopSweepReceipt`` that attests the listing was complete; it must belong to ``run`` at
    ``observed_at``, and the reading names it. A pull request whose number, state, draft flag or base
    is missing leaves the count unknown.
    """
    proof = _receipt_for(receipt, run, observed_at)
    if proof is None:
        return None
    seen: set[int] = set()
    count = 0
    for pull in pulls:
        fields = _fields(pull)
        if fields is None:
            return None
        number, state, draft, target = fields
        if number in seen:
            raise ValueError(f"pull request {number} listed twice")
        seen.add(number)
        if state == "open" and not draft and target == base:
            count += 1
    return {"id": f"queue@{observed_at}", "run": run, "observed_at": observed_at, "count": count, "source": source,
            "receipt": proof}
