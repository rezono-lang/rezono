"""Project delivery status from evidence scoped to one step and run."""

from collections.abc import Iterable, Mapping
from typing import Literal


StatusState = Literal["pending", "success", "failure"]


def project_with_reasons(
    step: Mapping[str, str], evidence: Iterable[Mapping[str, str]]
) -> tuple[StatusState, set[str]]:
    """Return the state and the current step's supporting evidence references."""
    scope = {key: step[key] for key in ("tenant", "delivery", "step", "run")}
    reasons: dict[str, set[str]] = {}
    for row in evidence:
        if row.get("reason") and all(row.get(key) == value for key, value in scope.items()):
            reasons.setdefault(row.get("relation", ""), set()).add(row["reason"])
    if "stuck" in reasons:
        return "failure", reasons["stuck"]
    if "done" in reasons:
        return "success", reasons["done"]
    return "pending", reasons.get("planned", set()) | reasons.get("waiting", set())


def project(step: Mapping[str, str], evidence: Iterable[Mapping[str, str]]) -> StatusState:
    """Use only evidence for the same tenant, delivery, step and run."""
    state, _ = project_with_reasons(step, evidence)
    return state
