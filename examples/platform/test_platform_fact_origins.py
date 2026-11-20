"""Every fact row of the platform has an origin (decisions/fact-origin-required.md, sections 1 and 2).

Judged here, independently of the compiler's W113 and R053, from the compiler's source entries and the pack's
schema. A row has an origin when one of its sources has a kind other than `pack` or `scenario` and is not a `git`
locator of one of the platform's own fact files; when its record has an arrow to std-decision's `Decision` with a
value; or when it belongs to a `Decision` record that names its decider and its day.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rezono_compiler import pack, sources

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parents[1]
FACTS = (PLATFORM / "facts").resolve()
NO_ORIGIN = {"pack", "scenario"}
DECISION = "decision"  # the kind of std-decision's Decision


class MissingFactOrigin(AssertionError):
    """A fact row of the platform has only its own file and line as its origin."""


def record(model, relation: str, key: list) -> tuple:
    """The record a row belongs to: the root kind of the relation's kind, and the identifier."""
    owner = relation.split("__", 1)[0]
    return (model.root(owner) if owner in model.kinds else owner), (key[0] if key else None)


def own_file(source: dict) -> bool:
    """A `git` locator of one of the platform's own fact files: the row citing itself."""
    path = str(source.get("position", "")).partition("#")[0]
    return source.get("kind") == "git" and bool(path) and (REPO / path).resolve().parent == FACTS


def cited(entry: dict) -> bool:
    return any(s.get("kind") not in NO_ORIGIN and not own_file(s) for s in entry["sources"])


@pytest.mark.xfail(
    strict=True,
    raises=MissingFactOrigin,
    reason="M2: decisions/fact-origin-required.md: Give every row of examples/platform/facts/ an origin: a sidecar or "
           "an @ citation that names the decision file, vendor publication or observation it comes from (kind git, "
           "document, tool, query or person; never pack), an arrow to the std-decision Decision that sets it, or a "
           "Decision record with decider and decided_on. Today 20 of the 40 fact files, among them core.yaml, have "
           "only their file and line. Read sections 1, 2 and 6.",
)
def test_every_platform_fact_row_has_an_origin():
    model = pack.read(PLATFORM)
    entries = sources.read(model, PLATFORM)
    rows = [(entry["row"]["relation"], json.loads(entry["row"]["key"])) for entry in entries]
    decision_kinds = {k for k in model.kinds if DECISION in model.ancestors(k)}
    arrows = {slot.table for kind in model.kinds.values() for slot in kind.slots.values()
              if slot.arrow and slot.range in decision_kinds}
    bound = {record(model, relation, key) for relation, key in rows if relation in arrows}
    decided = ({key[0] for relation, key in rows if relation == f"{DECISION}__decider"}
               & {key[0] for relation, key in rows if relation == f"{DECISION}__decided_on"})
    bound |= {(DECISION, identifier) for identifier in decided}

    missing: dict[str, set] = {}
    for entry, (relation, key) in zip(entries, rows):
        if cited(entry) or record(model, relation, key) in bound:
            continue
        place = next((s["name"] for s in entry["sources"] if s.get("kind") == "pack"), relation)
        missing.setdefault(place, set()).add(record(model, relation, key))
    if missing:
        raise MissingFactOrigin("records whose rows have only their own file and line as origin, by fact file: "
                                + "; ".join(f"{place}: {len(found)}" for place, found in sorted(missing.items())))
