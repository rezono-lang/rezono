"""Report one accepted delivery step through its configured status transport."""

from collections.abc import Callable, Iterable, Mapping

from loop.forgejo_read import read_status
from loop.forgejo_write import write_status
from loop.status_context import context
from loop.status_projection import project_with_reasons
from loop.status_retry import Status, StatusKey, publish
from loop.status_target import target


def report_step(
    request: Callable[..., object],
    owner: str,
    repo: str,
    proposal: Mapping[str, object],
    step: Mapping[str, str],
    observations: Iterable[Mapping[str, str]],
) -> None:
    """Publish a grounded status for an accepted proposal, reading before each write."""
    sha = target(proposal)
    if sha is None:
        return
    key = context(sha, step["tenant"], step["delivery"], step["step"])
    state, reasons = project_with_reasons(step, observations)
    if not reasons:
        return

    def read(key: StatusKey) -> Status | None:
        return read_status(request, owner, repo, *key)

    def write(key: StatusKey, value: Status) -> None:
        write_status(request, owner, repo, *key, value)

    # The provider accepts one link. A stable choice keeps retries independent of input order.
    publish(key, {"state": state, "evidence": min(reasons)}, read, write)
