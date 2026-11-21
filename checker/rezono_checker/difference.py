"""Check the difference of a proposal or variant against its base, for one role (step 7).

The publisher compares the role's two snapshots and writes the changes as key-range trees
(rezono_publisher.difference). This module trusts none of it: it compares the snapshots itself and requires
each tree to hold exactly the changes of its relation, in key order (text by its UTF-8 bytes, sorted here on
the encoded bytes), with the counts that go with them, in pieces within the limits, each named by the
sha256 of its bytes, with no piece left over and no tree for a relation that did not change.

When a compiled schema bundle (`bundle/schema-bundle.json`) is given, classification follows the schema's
declared cardinality (decisions/viewer-slip.md, "When a row is the same row"):
- a multivalued schema slot (`multivalued: true` in `attributes` or `arrows`) treats every row as an
  independent set membership (`added` or `removed`) and never pairs distinct values as `changed`;
- a single-valued schema slot (`multivalued: false`) pairs a value replacement for the same owner key
  (`key[:-1]`) with one row on each side as a single `changed` entry with `was`;
- a kind membership relation (`kinds`, arity 1) always emits `added` / `removed`;
- any other multi-column relation pairs by unique key prefix (`key[:-1]`) when one row exists on each side.
"""

from __future__ import annotations

from collections import defaultdict

from .canon import strict_json_loads
from .proof import _Walk
from .snapshots import read_rows

CHANGES = ("added", "removed", "changed")


def _bundle_schema(bundle: object) -> tuple[dict[str, bool], frozenset[str], list[str]]:
    """Extract slot cardinality (`table -> multivalued`) and kind tables from a schema bundle, failing closed."""
    if not isinstance(bundle, dict):
        return {}, frozenset(), ["difference: malformed schema bundle"]
    fmt = bundle.get("format")
    if fmt is not None and fmt != "rezono.schema-bundle/1":
        return {}, frozenset(), ["difference: malformed schema bundle format"]
    if not any(section in bundle for section in ("kinds", "attributes", "arrows")):
        return {}, frozenset(), ["difference: malformed schema bundle"]
    cardinality: dict[str, bool] = {}
    for section in ("attributes", "arrows"):
        if section not in bundle:
            continue
        items = bundle[section]
        if not isinstance(items, list):
            return {}, frozenset(), [f"difference: malformed schema bundle {section}"]
        for entry in items:
            if not isinstance(entry, dict):
                return {}, frozenset(), [f"difference: malformed schema bundle {section} entry"]
            table = entry.get("table")
            mv = entry.get("multivalued")
            if not isinstance(table, str) or not table or type(mv) is not bool:
                return {}, frozenset(), [f"difference: malformed schema bundle {section} entry"]
            if table in cardinality:
                return {}, frozenset(), [f"difference: duplicate schema slot table {table!r}"]
            cardinality[table] = mv
    kind_tables: set[str] = set()
    if "kinds" in bundle:
        kinds = bundle["kinds"]
        if not isinstance(kinds, list):
            return {}, frozenset(), ["difference: malformed schema bundle kinds"]
        for entry in kinds:
            if not isinstance(entry, dict):
                return {}, frozenset(), ["difference: malformed schema bundle kinds entry"]
            table = entry["table"] if "table" in entry else entry.get("id")
            if not isinstance(table, str) or not table:
                return {}, frozenset(), ["difference: malformed schema bundle kinds entry"]
            if table in cardinality or table in kind_tables:
                return {}, frozenset(), [f"difference: duplicate schema table {table!r}"]
            kind_tables.add(table)
    return cardinality, frozenset(kind_tables), []


def changes(before: bytes, after: bytes, *, multivalued: bool = False) -> list[dict]:
    """The changes of one relation, in key order by bytes.

    When `multivalued` is True, every row is an independent membership (`added` or `removed`) and rows
    with distinct values never pair as `changed`.
    """
    if type(multivalued) is not bool:
        raise ValueError("multivalued must be a bool")
    read_rows(before, "json")  # a malformed snapshot raises
    read_rows(after, "json")
    sides = []
    for data in (before, after):
        by_prefix = defaultdict(set)
        for r in strict_json_loads(data):
            k = tuple(r["key"])
            group = (True, k[:-1]) if (not multivalued and len(k) > 1) else (False, k)
            by_prefix[group].add(k)
        sides.append(by_prefix)
    old, new = sides
    out = []
    for prefix in set(old) | set(new):
        o, n = old.get(prefix, set()), new.get(prefix, set())
        if prefix[0] and len(o) == 1 and len(n) == 1 and o != n:
            out.append({"key": list(next(iter(n))), "change": "changed", "was": list(next(iter(o)))})
            continue
        out += [{"key": list(k), "change": "removed"} for k in o - n]
        out += [{"key": list(k), "change": "added"} for k in n - o]
    return sorted(out, key=lambda e: [p.encode() for p in e["key"]])


def check_difference(
    before: dict,
    after: dict,
    pieces: dict,
    counts: dict,
    roots: dict,
    limit: int,
    fanout: int,
    bundle: dict | None = None,
) -> list[str]:
    """Problems with one role's difference; empty when it is exactly the change from `before` to `after`.

    `before` and `after` are the role's snapshot bytes per relation (a relation on one side only counts as
    empty on the other), `pieces` the bytes per path, `counts` {relation: {added, removed, changed}} and
    `roots` {relation: {"file", "sha256", "levels"}}, both only for relations that changed. When `bundle`
    (the compiled `bundle/schema-bundle.json`) is given, slot cardinality from `attributes` and `arrows`
    governs pairing (`multivalued: true` never emits `changed`; `multivalued: false` requires `changed`)."""
    if bundle is not None:
        slot_cardinality, kind_tables, bundle_problems = _bundle_schema(bundle)
        if bundle_problems:
            return bundle_problems
    else:
        slot_cardinality, kind_tables = {}, frozenset()
    problems: list[str] = []
    walk = _Walk(pieces, limit, fanout, problems)
    for rel in sorted(set(before) | set(after) | set(counts) | set(roots)):
        independent = slot_cardinality.get(rel, False) or rel in kind_tables
        want = changes(before.get(rel, b"[]"), after.get(rel, b"[]"), multivalued=independent)
        if not want:
            if rel in counts or rel in roots:
                problems.append(f"difference/{rel}: listed, but the relation did not change")
            continue
        tally = {c: sum(e["change"] == c for e in want) for c in CHANGES}
        if counts.get(rel) != tally or any(type(v) is not int for v in counts[rel].values()):
            problems.append(f"difference/{rel}: the counts are not {tally}")
        if rel not in roots:
            problems.append(f"difference/{rel}: no tree")
            continue
        got = walk.root(f"difference/{rel}", roots[rel])
        if got is not None and got != want:
            problems.append(f"difference/{rel}: the entries are not the change between the role's snapshots")
    walk.unreached()
    return problems
