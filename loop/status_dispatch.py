"""Report one accepted delivery step through its configured status transport."""

from collections.abc import Callable, Iterable, Mapping

from rezono_canon import canonical_sha256

from loop.forgejo_read import read_status
from loop.forgejo_write import write_status
from loop.status_context import context
from loop.status_projection import StatusProjection, project_status
from loop.status_retry import Status, StatusKey, publish
from loop.status_target import target
from loop.typed_recording import instant


def report_step(
    request: Callable[..., object],
    owner: str,
    repo: str,
    proposal: Mapping[str, object],
    step: Mapping[str, str],
    observations: Iterable[Mapping[str, str]],
    *,
    publish_evidence: Callable[[StatusProjection], str] | None = None,
) -> None:
    """Publish a grounded status, reading before each write.

    An evidence port stores a projection by its snapshot ID and returns the stable URL
    for the complete proof. A single source can be linked directly.
    """
    sha = target(proposal)
    if sha is None:
        return
    key = context(sha, step["tenant"], step["delivery"], step["step"])
    projection = project_status(step, observations)
    if not projection.reasons or (publish_evidence is None and len(projection.reasons) != 1):
        return

    evidence = publish_evidence(projection) if publish_evidence is not None else next(iter(projection.reasons))
    if not evidence:
        raise ValueError("status evidence must have a publication link")
    value = {"state": projection.state, "evidence": evidence}

    # The provider retains the event instant with the status across client processes.
    prefix = f"Rezono event {canonical_sha256(step['run'])} "
    at = instant(projection.latest_at) if projection.latest_at else None
    if at is not None:
        value["description"] = prefix + projection.latest_at

    def read(key: StatusKey) -> Status | None:
        return read_status(request, owner, repo, *key)

    def write(key: StatusKey, value: Status) -> None:
        write_status(request, owner, repo, *key, value)

    def supersedes(latest: Status) -> bool:
        description = latest.get("description", "")
        if not description.startswith(prefix):
            return False
        previous_at = instant(description[len(prefix):])
        return (at is None or previous_at > at
                or (previous_at == at and latest["state"] == value["state"] and latest["evidence"] == evidence))

    publish(key, value, read, write, supersedes=supersedes)
