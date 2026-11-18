"""Compare independent observations for one recorded flow case."""

from collections.abc import Iterable, Mapping
from typing import Literal


def assess(
    case: Mapping[str, str | int], observations: Iterable[Mapping[str, str | int]]
) -> tuple[Literal["confirmed", "disagreement", "incomplete"], tuple[str, ...]]:
    """Classify the case and retain the probe and Hubble references in that order."""
    scope = {key: case[key] for key in ("run", "id", "source", "destination", "port", "protocol")}
    expected = case["expected"]
    if expected not in ("allow", "deny"):
        raise ValueError("expected flow outcome must be allow or deny")

    probe = []
    hubble = []
    for row in observations:
        if any(row.get(key) != value for key, value in scope.items()):
            continue
        if row.get("witness") == "probe":
            probe.append(row)
        elif row.get("witness") == "hubble":
            hubble.append(row)

    if len(probe) != 1 or len(hubble) != 1:
        return "incomplete", ()
    references = []
    outcomes = []
    for row in (probe[0], hubble[0]):
        reference = row.get("ref")
        outcome = row.get("outcome")
        if not isinstance(reference, str) or not reference or outcome not in ("allow", "deny"):
            return "incomplete", ()
        references.append(reference)
        outcomes.append(outcome)

    if references[0] == references[1]:
        return "incomplete", ()
    if all(outcome == expected for outcome in outcomes):
        return "confirmed", tuple(references)
    return "disagreement", tuple(references)
