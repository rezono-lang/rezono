"""Project delivery status from evidence scoped to one step and run."""

from collections.abc import Iterable, Mapping
from typing import Literal


def project(
    step: Mapping[str, str], evidence: Iterable[Mapping[str, str]]
) -> Literal["pending", "success", "failure"]:
    """Use only evidence for the same tenant, delivery, step and run."""
    scope = {key: step[key] for key in ("tenant", "delivery", "step", "run")}
    relations = {
        row.get("relation")
        for row in evidence
        if row.get("reason") and all(row.get(key) == value for key, value in scope.items())
    }
    if "stuck" in relations:
        return "failure"
    if "done" in relations:
        return "success"
    return "pending"
