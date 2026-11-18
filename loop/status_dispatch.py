"""Report one accepted delivery step through its configured status transport."""

from collections.abc import Callable, Iterable, Mapping

from loop.forgejo_read import read_status
from loop.forgejo_write import write_status
from loop.status_context import context
from loop.status_projection import StatusProjection, project_status
from loop.status_retry import Status, StatusKey, publish
from loop.status_target import target


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
    for the complete proof. Existing transports may still link directly to a source.
    """
    sha = target(proposal)
    if sha is None:
        return
    key = context(sha, step["tenant"], step["delivery"], step["step"])
    projection = project_status(step, observations)
    if not projection.reasons:
        return

    def read(key: StatusKey) -> Status | None:
        return read_status(request, owner, repo, *key)

    def write(key: StatusKey, value: Status) -> None:
        write_status(request, owner, repo, *key, value)

    # The status provider accepts one URL. Prefer the complete proof when an evidence port is configured.
    evidence = publish_evidence(projection) if publish_evidence else min(projection.reasons)
    if not evidence:
        raise ValueError("status evidence must have a publication link")
    publish(key, {"state": projection.state, "evidence": evidence}, read, write)
