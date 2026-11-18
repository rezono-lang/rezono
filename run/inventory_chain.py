"""Normalize observed pages and read complete inventories through the cleanup pack."""

import json
from collections import Counter, defaultdict
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import TypedDict

from jsonschema import Draft202012Validator

from rezono_compiler import batch, pack, rules


class Resource(TypedDict):
    id: str
    plan_hash: str | None


class Page(TypedDict):
    sweep_id: str
    page_id: str
    next_page_id: str | None
    resources: list[Resource]


Facts = dict[str, list[tuple[str | int, ...]]]
_RUN = Path(__file__).parent
_PAGE = Draft202012Validator(json.loads(
    (_RUN / "schemas" / "inventory-page.json").read_text(encoding="utf-8")
))


def page_facts(pages: Iterable[Page], sweep_id: str, root_page_id: str) -> Facts | None:
    """Project page responses without interpreting their links or asserting coverage."""
    if not isinstance(sweep_id, str) or not sweep_id or not isinstance(root_page_id, str) or not root_page_id:
        return None
    facts: Facts = defaultdict(list)
    facts["sweep"].append((sweep_id,))
    facts["sweep__root_token"].append((sweep_id, root_page_id))
    occurrences: Counter[str] = Counter()
    for page in pages:
        if not isinstance(page, dict):
            return None
        observed_sweep = page.get("sweep_id")
        if not isinstance(observed_sweep, str) or not observed_sweep:
            return None
        if observed_sweep != sweep_id:
            continue
        if not _PAGE.is_valid(page):
            return None
        token = page["page_id"]
        # Tokens can recur in different sweeps, or even in two conflicting replies.
        key = [sweep_id, token, occurrences[token]]
        occurrences[token] += 1
        row = json.dumps(key, separators=(",", ":"))
        facts["page"].append((row,))
        facts["page__sweep"].append((row, sweep_id))
        facts["page__token"].append((row, token))
        facts["page__next_token"].append((row, page["next_page_id"] or ""))
        facts["page__item_count"].append((row, len(page["resources"])))
        for index, resource in enumerate(page["resources"]):
            item = json.dumps([*key, index], separators=(",", ":"))
            facts["resource"].append((item,))
            facts["resource__sweep"].append((item, sweep_id))
            facts["resource__page"].append((item, row))
            facts["resource__provider_id"].append((item, resource["id"]))
            if resource["plan_hash"] is None:
                facts["resource__tag_state"].append((item, "untagged"))
            else:
                facts["resource__plan_hash"].append((item, resource["plan_hash"]))
    return dict(facts)


@cache
def _program():
    return rules.load(pack.read(_RUN / "packs" / "cleanup").rules)


def resources(
    pages: Iterable[Page], sweep_id: str, root_page_id: str
) -> list[Resource] | None:
    """Read resources in provider order once the rules prove a complete chain."""
    pages = list(pages)
    facts = page_facts(pages, sweep_id, root_page_id)
    if facts is None:
        return None
    program = _program()
    connection = batch.connect(program, facts)
    try:
        batch.compute(connection, program)
        if not batch.read(connection, program, ["complete_inventory"])["complete_inventory"]:
            return None
    finally:
        connection.close()

    by_token = {p["page_id"]: p for p in pages if p["sweep_id"] == sweep_id}
    ordered: list[Resource] = []
    token: str | None = root_page_id
    while token is not None:
        page = by_token[token]
        ordered.extend(resource.copy() for resource in page["resources"])
        token = page["next_page_id"]
    return ordered
