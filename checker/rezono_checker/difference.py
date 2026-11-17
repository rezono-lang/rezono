"""Check the difference of a proposal or variant against its base, for one role (decision R10, step 7).

The publisher compares the role's two snapshots and writes the changes as key-range trees
(rezono_publisher.difference). This module trusts none of it: it compares the snapshots itself and requires
each tree to hold exactly the changes of its relation, in key order (text by its UTF-8 bytes, sorted here on
the encoded bytes), with the counts that go with them, in pieces within the limits, each named by the
sha256 of its bytes, with no piece left over and no tree for a relation that did not change.

A change is a row in one snapshot only (`added`, `removed`), except a changed cell: a key of two or more
columns whose prefix holds exactly one row in each snapshot, and those differ (`changed`, with `was`).
"""

from __future__ import annotations

import json
from collections import defaultdict

from .proof import _Walk
from .snapshots import read_rows

CHANGES = ("added", "removed", "changed")


def changes(before: bytes, after: bytes) -> list[dict]:
    """The changes of one relation, in key order by bytes."""
    read_rows(before, "json")  # a malformed snapshot raises
    read_rows(after, "json")
    sides = []
    for data in (before, after):
        by_prefix = defaultdict(set)
        for r in json.loads(data):
            k = tuple(r["key"])
            by_prefix[(True, k[:-1]) if len(k) > 1 else (False, k)].add(k)  # a cell, or a row of one column
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


def check_difference(before: dict, after: dict, pieces: dict, counts: dict, roots: dict, limit: int, fanout: int) -> list[str]:
    """Problems with one role's difference; empty when it is exactly the change from `before` to `after`.

    `before` and `after` are the role's snapshot bytes per relation (a relation on one side only counts as
    empty on the other), `pieces` the bytes per path, `counts` {relation: {added, removed, changed}} and
    `roots` {relation: {"file", "sha256", "levels"}}, both only for relations that changed."""
    problems: list[str] = []
    walk = _Walk(pieces, limit, fanout, problems)
    for rel in sorted(set(before) | set(after) | set(counts) | set(roots)):
        want = changes(before.get(rel, b"[]"), after.get(rel, b"[]"))
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
