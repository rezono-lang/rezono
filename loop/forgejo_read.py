"""Read a commit status using the configured, injected Forgejo transport."""

from collections.abc import Callable, Mapping
from itertools import count
from urllib.parse import quote

from loop.status_target import is_commit_sha


def read_status(
    request, owner: str, repo: str, sha: str, context: str, *,
    page_size: int = 50, blocks_write: Callable[[dict[str, str]], bool] | None = None,
) -> dict[str, str] | None:
    """Return the newest matching status or an older one that blocks the write."""
    if not is_commit_sha(sha):
        raise ValueError("commit must be a full SHA")
    if type(page_size) is not int or page_size <= 0:
        raise ValueError("page size must be a positive integer")
    for segment in (owner, repo):
        if not isinstance(segment, str) or not segment or segment in (".", "..") or "/" in segment:
            raise ValueError("owner and repository must be individual path segments")
    if not isinstance(context, str) or not context:
        raise ValueError("status context is required")

    path = f"/api/v1/repos/{quote(owner, safe='')}/{quote(repo, safe='')}/commits/{sha}/statuses"
    latest = None
    previous_page = None
    seen_ids = set()
    for page in count(1):
        rows = request("GET", path, query={"page": page, "limit": page_size})
        if not isinstance(rows, list):
            raise ValueError("expected a page of commit statuses")
        # The provider may cap its page size below the requested limit.
        if not rows:
            return latest
        if rows == previous_page:
            raise ValueError("commit status history did not advance")
        previous_page = rows
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("expected a commit status record")
            provider_id = row.get("id")
            if provider_id is not None:
                if type(provider_id) is not int or provider_id <= 0 or provider_id in seen_ids:
                    raise ValueError("commit status history has an invalid or repeated provider ID")
                seen_ids.add(provider_id)
            if row.get("context") != context:
                continue
            state, evidence = row.get("status"), row.get("target_url")
            if not isinstance(state, str) or not state or not isinstance(evidence, str):
                raise ValueError("matching commit status lacks state or evidence")
            status = {"state": state, "evidence": evidence}
            description = row.get("description")
            if description is not None and not isinstance(description, str):
                raise ValueError("matching commit status has an invalid description")
            if description:
                status["description"] = description
            if blocks_write is None or blocks_write(status):
                return status
            if latest is None:
                latest = status
