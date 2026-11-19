"""Apply the SubmitOne guards of formal/Rounds.tla to a round state.

A submission records the claimed member, its worker, the current pin and the
certificate pin it was chosen under. Submission is not completion: only a
matching readback at the current pin adds a member to ``done``.
"""

from copy import deepcopy
from typing import Any


def _submitted(state: dict[str, Any], member: str) -> bool:
    return any(entry.get("member") == member for entry in state["submitted"])


def submit_refusal(state: dict[str, Any], *, worker: str, member: str) -> str | None:
    """Return None when ``worker`` may submit ``member``, else the first failed guard.

    A missing ``stopped`` or ``submitted`` set is unknown, not empty: the guard
    cannot be checked, so the submission is refused.
    """
    if state["chosen"]["pin"] != state["pin"]:
        return "stale_certificate"
    if member not in state.get("pending", []):
        return "not_pending"
    if state.get("claims", {}).get(member) != worker:
        return "not_claimant"
    if state.get("stopped") is None:
        return "stopped_unknown"
    if worker in state["stopped"]:
        return "worker_stopped"
    if state.get("submitted") is None:
        return "submitted_unknown"
    if _submitted(state, member):
        return "already_submitted"
    return None


def record_submit(state: dict[str, Any], *, worker: str, member: str) -> dict[str, Any]:
    """Return a new state with the submission appended; ``done`` is unchanged."""
    refusal = submit_refusal(state, worker=worker, member=member)
    if refusal is not None:
        raise ValueError(f"submit refused: {refusal}")
    after = deepcopy(state)
    after["submitted"] = [
        *after["submitted"],
        {
            "member": member,
            "worker": worker,
            "pin": deepcopy(state["pin"]),
            "certificate": deepcopy(state["chosen"]["pin"]),
        },
    ]
    return after
