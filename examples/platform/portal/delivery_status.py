"""Render recorded delivery evidence as a proposal commit status."""

import re
from typing import Literal, TypedDict


State = Literal["pending", "success", "failure"]
_SLUG = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


class ObservedDelivery(TypedDict):
    sha: str
    tenant: str
    delivery: str
    step: str
    state: State
    eventTime: str


class CommitStatus(TypedDict):
    sha: str
    context: str
    state: State
    eventTime: str


def render(observed: ObservedDelivery) -> CommitStatus:
    """Keep the recorded state and event time on the pinned proposal commit."""
    sha = observed["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("delivery status requires a full proposal commit ID")
    segments = (observed["tenant"], observed["delivery"], observed["step"])
    if any(not _SLUG.fullmatch(segment) for segment in segments):
        raise ValueError("tenant, delivery and step must be lowercase ASCII slugs")
    state = observed["state"]
    if state not in ("pending", "success", "failure"):
        raise ValueError("unsupported delivery state")
    return {
        "sha": sha,
        "context": "rezono/delivery/" + "/".join(segments),
        "state": state,
        "eventTime": observed["eventTime"],
    }
