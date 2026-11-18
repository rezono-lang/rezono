"""Bind the local request bytes to their recorded Git source."""

from collections.abc import Mapping
from hashlib import sha256
import json
import re
from typing import TypedDict


class Source(TypedDict):
    repository: str
    commit: str
    path: str
    sha256: str


class SourcedRequest(TypedDict):
    request: dict[str, object]
    source: Source


def load_request(raw: bytes, provenance: Mapping[str, object], digest: str) -> SourcedRequest:
    """Verify exact bytes and an immutable source before decoding the request."""
    repository = provenance.get("repository")
    commit = provenance.get("commit")
    path = provenance.get("path")
    if not isinstance(repository, str) or not repository.strip():
        raise ValueError("request provenance requires a repository")
    if not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("request provenance requires a full lowercase Git commit")
    if (not isinstance(path, str) or not path or "\\" in path or ":" in path or "\0" in path
            or any(segment in {"", ".", ".."} for segment in path.split("/"))):
        raise ValueError("request provenance requires a repository-relative file path")
    if sha256(raw).hexdigest() != digest:
        raise ValueError("request bytes do not match the source SHA-256 digest")

    request = json.loads(raw.decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    return {
        "request": request,
        "source": {"repository": repository, "commit": commit, "path": path, "sha256": digest},
    }
