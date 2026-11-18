"""Render a normalized tenant request as a repository-relative JSON file."""

import json
import re


_SEGMENT = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def render(team: str, service: str, request: dict[str, object]) -> tuple[str, str]:
    """Return the team and service path and deterministic JSON for the request."""
    if not _SEGMENT.fullmatch(team) or not _SEGMENT.fullmatch(service):
        raise ValueError("team and service must be lowercase path slugs")
    path = f"teams/{team}/{service}/request.json"
    body = json.dumps(request, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2)
    return path, body + "\n"
