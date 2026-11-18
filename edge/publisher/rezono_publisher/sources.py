"""The sources of the base rows one role reads (S25, docs/compiler.md#provenance-per-fact-s25).

Input is the compiler's entries for the epoch's facts (`rezono_compiler.sources.read`, the content of
`generated/sources.json`): one `SourceEntry` per base row, its key the canonical JSON of the typed parts.
Per role the publisher keeps exactly the entries of the rows in that role's snapshots, keyed as the
snapshot and the proofs key the row (text parts), sorted on relation and key with their sources
sorted and without duplicates. Access follows the fact: a role gets a row's sources only with the row.

These entries are not the manifest's `sources` (where each source stood when the epoch closed); they say
where a row came from. A source is a locator: not content, not proof that the row is true, and not proof
of its real origin or of who decided it (principle 10, R13). Whether a role's entries are right is the
checker's (`rezono_checker.sources`), which derives the rows itself.
"""
from __future__ import annotations

import json

from rezono_canon import canonical_json

SOURCES = "rezono:sources"  # the check of every role's source entries by the checker; not a relation name


class Stale(ValueError):
    """The compiler's entries do not belong to the epoch's rows."""


def snapshot_key(key: str) -> str:
    """The compiler's canonical key as the snapshot's key text. rezono_canon writes integers and dates as text
    already; only a boolean differs (`true` against `"true"`). The relation keeps the parts typed: `"1"` in an
    integer kind and in a text kind are two rows of two relations."""
    parts = json.loads(key)
    if not isinstance(parts, list) or not all(isinstance(p, (str, bool)) for p in parts):
        raise Stale("a source entry's key is not the canonical JSON of its parts")
    return canonical_json([("true" if p else "false") if isinstance(p, bool) else p for p in parts])


def utf16(text: str) -> bytes:
    return text.encode("utf-16-be")  # C1 orders by UTF-16 code units, as the compiler's entries are


def index(entries: list) -> dict[tuple[str, str], dict]:
    """The compiler's entries by (relation, snapshot key), each a private copy with its sources in canonical
    order and without duplicates. Two entries for one row block: the compiler gives one per row."""
    out: dict[tuple[str, str], dict] = {}
    for e in json.loads(json.dumps(entries)):
        row = e.get("row") if isinstance(e, dict) else None
        if not isinstance(row, dict) or not isinstance(row.get("relation"), str) or not isinstance(row.get("key"), str):
            raise Stale("a source entry has no row reference")
        ref = (row["relation"], snapshot_key(row["key"]))
        if ref in out:
            raise Stale(f"two source entries for one row of {ref[0]}")
        sources = {canonical_json(s): s for s in e.get("sources") or []}
        out[ref] = {"row": {"relation": ref[0], "key": ref[1]},
                    "sources": [sources[k] for k in sorted(sources, key=utf16)],
                    **({"reason": e["reason"]} if "reason" in e else {})}
    return out


def check_stale(entries: dict, rows: dict, key_text) -> None:
    """Every entry names a row of the epoch: an entry without its row is not about this epoch's facts."""
    have = {(rel, key_text(r)) for rel, rs in rows.items() for r in rs}
    if any(ref not in have for ref in entries):
        raise Stale("a source entry names a row the epoch does not have")


def for_role(entries: dict, rows: dict, key_text) -> list[dict]:
    """The entries of exactly the rows this role reads (`rows`: relation -> its rows), in (relation, key)
    order. A row without an entry is not invented here: the checker finds it missing."""
    refs = [(rel, key_text(r)) for rel, rs in rows.items() for r in rs]
    return [entries[ref] for ref in sorted(set(refs), key=lambda x: (utf16(x[0]), utf16(x[1]))) if ref in entries]
