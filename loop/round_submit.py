"""Apply the SubmitOne guards of formal/Rounds.tla to a round state.

A submission records the claimed member, its worker, the current pin and the
certificate pin it was chosen under. Submission is not completion: only a
matching readback at the current pin adds a member to ``done``.
"""

from copy import deepcopy
from typing import Any


def _submitted(state: dict[str, Any], member: str) -> bool:
    return any(entry.get("member") == member for entry in state.get("submitted", []))


def submit_refusal(state: dict[str, Any], *, worker: str, member: str) -> str | None:
    """Return None when ``worker`` may submit ``member``, else the first failed guard."""
    if state["chosen"]["pin"] != state["pin"]:
        return "stale_certificate"
    if member not in state.get("pending", []):
        return "not_pending"
    if state.get("claims", {}).get(member) != worker:
        return "not_claimant"
    if worker in state.get("stopped", []):
        return "worker_stopped"
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
        *after.get("submitted", []),
        {
            "member": member,
            "worker": worker,
            "pin": deepcopy(state["pin"]),
            "certificate": deepcopy(state["chosen"]["pin"]),
        },
    ]
    return after
