"""Read one pull request answer per claim branch, and nothing from an unreadable answer."""

from collections.abc import Iterable, Mapping


def _is_open_pull_for(pull: object, branch: str) -> bool:
    if not isinstance(pull, Mapping) or pull.get("state") != "open":
        return False
    head = pull.get("head")
    return isinstance(head, Mapping) and head.get("ref") == branch


def _state(branch: str, answer: object) -> str | None:
    """Return "open", "none" or None when the answer is not a complete reading."""
    if not isinstance(answer, list):
        return None
    if not answer:
        return "none"
    if all(_is_open_pull_for(pull, branch) for pull in answer):
        return "open"
    return None


def pull_rows(
    claims: Iterable[Mapping[str, object]],
    answers: Mapping[str, object],
    *,
    observed_at: int,
    source: str,
) -> list[dict[str, object]]:
    """Return BuildClaimPullReading records, ordered by claim branch."""
    branches = sorted({claim["branch"] for claim in claims if isinstance(claim.get("branch"), str)})
    rows: list[dict[str, object]] = []
    for branch in branches:
        if branch not in answers:
            continue
        state = _state(branch, answers[branch])
        if state is None:
            continue
        rows.append(
            {
                "id": f"{branch}@{observed_at}",
                "claim": branch,
                "observed_at": observed_at,
                "state": state,
                "source": source,
            }
        )
    return rows
