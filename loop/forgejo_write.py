"""Write a status for the pinned proposal commit through a supplied transport."""

from collections.abc import Mapping
from typing import Protocol
from urllib.parse import quote


class StatusTransport(Protocol):
    def __call__(self, method: str, path: str, *, body: dict[str, str]) -> object: ...


def write_status(
    request: StatusTransport, owner: str, repo: str, sha: str, context: str, value: Mapping[str, str]
) -> object:
    """Send the projected status and return the provider acknowledgement."""
    repository = f"{quote(owner, safe='')}/{quote(repo, safe='')}"
    return request(
        "POST",
        f"/api/v1/repos/{repository}/statuses/{quote(sha, safe='')}",
        body={"context": context, "state": value["state"], "target_url": value["evidence"]},
    )
