"""Read one pull request answer per claim branch, and nothing from an unreadable or unproven answer."""

from collections.abc import Iterable, Mapping


def _is_open_pull_for(pull: object, branch: str) -> bool:
    if not isinstance(pull, Mapping) or pull.get("state") != "open":
        return False
    head = pull.get("head")
    return isinstance(head, Mapping) and head.get("ref") == branch


def _state(branch: str, answer: object) -> str | None:
    """Return "open", "empty" or None when the answer is not a reading."""
    if not isinstance(answer, list):
        return None
    if not answer:
        return "empty"
    if all(_is_open_pull_for(pull, branch) for pull in answer):
        return "open"
    return None


def _receipt_for(receipt: Mapping[str, object] | None, run: object, observed_at: int) -> str | None:
    """Return the receipt ID when it attests a complete read of this run at this cut."""
    if not isinstance(receipt, Mapping):
        return None
    name = receipt.get("id")
    if not isinstance(name, str) or not name.strip():
        return None
    if receipt.get("run") != run or type(receipt.get("event_time")) is not int:
        return None
    return name if receipt["event_time"] == observed_at else None


def pull_rows(
    claims: Iterable[Mapping[str, object]],
    answers: Mapping[str, object],
    *,
    observed_at: int,
    source: str,
    receipt: Mapping[str, object] | None,
) -> list[dict[str, object]]:
    """Return BuildClaimPullReading records, ordered by claim branch.

    An open pull request is read from the answer itself. An empty answer says ``none`` only when
    ``receipt``, a ``LoopSweepReceipt`` of the claim's run at ``observed_at``, attests that the read
    was complete. The reading names that receipt. Without one the answer stays unknown.
    """
    runs: dict[str, object] = {}
    for claim in claims:
        branch = claim.get("branch")
        if isinstance(branch, str) and runs.setdefault(branch, claim.get("run")) != claim.get("run"):
            raise ValueError(f"claim {branch} is listed for two runs")
    rows: list[dict[str, object]] = []
    for branch in sorted(runs):
        if branch not in answers:
            continue
        state = _state(branch, answers[branch])
        row: dict[str, object] = {"id": f"{branch}@{observed_at}", "claim": branch, "observed_at": observed_at}
        if state == "open":
            rows.append(dict(row, state="open", source=source))
        elif state == "empty":
            proof = _receipt_for(receipt, runs[branch], observed_at)
            if proof is not None:
                rows.append(dict(row, state="none", source=source, receipt=proof))
    return rows
