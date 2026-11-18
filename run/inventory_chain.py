"""Prove completeness from a single recorded, rooted inventory sweep."""

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator


class Resource(TypedDict):
    id: str
    plan_hash: str | None


class Page(TypedDict):
    sweep_id: str
    page_id: str
    next_page_id: str | None
    resources: list[Resource]


_PAGE = Draft202012Validator(json.loads(
    (Path(__file__).parent / "schemas" / "inventory-page.json").read_text(encoding="utf-8")
))


def resources(
    pages: Iterable[Page], sweep_id: str, root_page_id: str
) -> list[Resource] | None:
    """Return resources in chain order, or unknown for any incomplete sweep."""
    if not isinstance(sweep_id, str) or not sweep_id or not isinstance(root_page_id, str) or not root_page_id:
        return None
    remaining: dict[str, Page] = {}
    for page in pages:
        if not isinstance(page, dict):
            return None
        observed_sweep = page.get("sweep_id")
        if not isinstance(observed_sweep, str) or not observed_sweep:
            return None
        if observed_sweep != sweep_id:
            continue
        if not _PAGE.is_valid(page) or page["page_id"] in remaining:
            return None
        remaining[page["page_id"]] = page

    reached: list[Resource] = []
    tags_by_id: dict[str, str | None] = {}
    next_id: str | None = root_page_id
    while next_id is not None:
        page = remaining.pop(next_id, None)
        if page is None:
            return None
        for resource in page["resources"]:
            tag = resource["plan_hash"]
            if tags_by_id.setdefault(resource["id"], tag) != tag:
                return None
            reached.append(resource.copy())
        next_id = page["next_page_id"]

    return None if remaining else reached
