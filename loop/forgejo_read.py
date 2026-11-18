"""Read a commit status using the configured, injected Forgejo transport."""

from collections.abc import Mapping
from itertools import count
from urllib.parse import quote

from loop.status_target import is_commit_sha


def read_status(request, owner: str, repo: str, sha: str, context: str, *, page_size: int = 50) -> dict | None:
    """Return the first matching status from the provider's newest-first pages."""
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
    for page in count(1):
        rows = request("GET", path, query={"page": page, "limit": page_size})
        if not isinstance(rows, list):
            raise ValueError("expected a page of commit statuses")
        for row in rows:
            if not isinstance(row, Mapping):
                raise ValueError("expected a commit status record")
            if row.get("context") == context:
                state, evidence = row.get("status"), row.get("target_url")
                if not isinstance(state, str) or not state or not isinstance(evidence, str):
                    raise ValueError("matching commit status lacks state or evidence")
                return {"state": state, "evidence": evidence}
        if len(rows) < page_size:
            return None
