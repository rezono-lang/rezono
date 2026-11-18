"""Report one accepted delivery step through its configured status transport."""

import re
from collections.abc import Callable, Iterable, Mapping

from rezono_canon import canonical_sha256

from loop.forgejo_read import read_status
from loop.forgejo_write import write_status
from loop.status_context import context
from loop.status_projection import StatusProjection, project_status
from loop.status_retry import Status, StatusKey, publish
from loop.status_target import target
from loop.typed_recording import instant


EVENT_DESCRIPTION = "Rezono event "
FINGERPRINT = re.compile(r"[0-9a-f]{64}")


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
    run = canonical_sha256(step["run"])
    at = instant(projection.latest_at) if projection.latest_at else None
    if at is not None:
        # A source fingerprint identifies the earlier ground when a conflict is reported later.
        source = "-" if projection.conflicts else canonical_sha256(min(projection.reasons))
        value["description"] = f"{EVENT_DESCRIPTION}{run} {projection.latest_at} {source}"

    def read(key: StatusKey) -> Status | None:
        return read_status(request, owner, repo, *key, blocks_write=supersedes)

    def write(key: StatusKey, value: Status) -> None:
        write_status(request, owner, repo, *key, value)

    def supersedes(previous: Status) -> bool:
        description = previous.get("description", "")
        if not description.startswith(EVENT_DESCRIPTION):
            return False
        described_run, _, observed = description[len(EVENT_DESCRIPTION):].partition(" ")
        if not FINGERPRINT.fullmatch(described_run):
            raise ValueError("invalid run fingerprint in commit status history")
        if described_run != run:
            return False
        timestamp, _, source = observed.partition(" ")
        if source != "-" and not FINGERPRINT.fullmatch(source):
            raise ValueError("invalid source fingerprint in commit status history")
        previous_at = instant(timestamp)
        if at is None or previous_at > at:
            return True
        if previous_at < at:
            return False
        return publish_evidence is None or not any(
            state == previous["state"] and canonical_sha256(reason) == source
            for state, reason in projection.conflicts
        )

    publish(key, value, read, write, supersedes=supersedes)
