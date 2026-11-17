"""The check `rezono:sources` (S25, docs/compiler.md#provenance-per-fact-s25): the sources one role gets.

Input is plain data: the bytes of the role's source-entry file (a list of `SourceEntry`, contracts/source.yaml),
the schema bundle and the bytes of the role's published snapshots, by relation. Independent of the publisher:
the base rows come from the bundle's kind, arrow and attribute tables and the very snapshot bytes the role
gets, never from what the publisher selected. Every finding blocks.

- The entries name exactly the base rows of the role's snapshots, by their typed RowRef (relation and
  canonical key), in (relation, key) order (C1, by UTF-16 code units), each once: no entry for a row the
  role does not read (O8), none missing.
- Each has at least one source, in canonical order without duplicates, and each source has its kind's fields.

A source's metadata is the declared unit that belongs to its row: it follows the readable row as a whole,
and nothing about a hidden row enters it or decides it (S25 as made precise by the owner on 08-11-2026,
#329). So no text of a source is compared with the ids of hidden elements: a line 3 is not the element
B/3, and equal text is no access relation. The check reads only the role's own snapshots, so hidden rows
cannot change its outcome. A finding never names a row the role does not read and never counts such rows.
A source is a locator; this check says nothing about whether the row is true or where it really came from
(principle 10, R13).
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re

from rezono_canon import canonical_json

from .snapshots import read_rows

# contracts/source.yaml, restated so the oracle does not read the publisher's or compiler's copy
# (a test holds it to the contract).
KINDS = {"git", "pack", "scenario", "proposal", "query", "tool", "person", "document"}
OWNERSHIP = {"first_party", "third_party"}
FIELDS = {"kind", "name", "revision", "position", "url", "retrieved_at", "fragment_sha256", "ownership",
          "licence", "attribution"}
URL = re.compile(r"^https?://[^\s/?#]+([/?#][^\s]*)?$")
INSTANT = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(\.[0-9]{1,6})?Z$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
TRIMMED = re.compile(r"^\S(.*\S)?$", re.S)


def utf16(text: str) -> bytes:
    return text.encode("utf-16-be")


def tables(bundle) -> set:
    """The base tables of facts: those of the kinds, arrows and attributes. Enum and parameter rows are schema."""
    doc = json.loads(bundle) if isinstance(bundle, (str, bytes)) else bundle
    return {s["table"] for part in ("kinds", "arrows", "attributes") for s in doc.get(part) or []}


def source_problem(s) -> str:
    """Which rule of contracts/source.yaml `Source` a source breaks, or ''."""
    if not isinstance(s, dict) or set(s) - FIELDS or not all(isinstance(v, str) for v in s.values()):
        return "shape"
    if not {"kind", "name", "position"} <= set(s) or s["kind"] not in KINDS:
        return "kind"
    if s["kind"] in {"git", "proposal"} and "revision" not in s:
        return "revision"
    if "url" in s and not URL.match(s["url"]):
        return "url"
    if "retrieved_at" in s:
        try:
            ok = bool(INSTANT.match(s["retrieved_at"])) and bool(datetime.datetime.fromisoformat(s["retrieved_at"]))
        except ValueError:
            ok = False
        if not ok:
            return "retrieved_at"
    if "fragment_sha256" in s and not SHA256.match(s["fragment_sha256"]):
        return "fragment_sha256"
    if "ownership" in s and s["ownership"] not in OWNERSHIP:
        return "ownership"
    if any(f in s and not TRIMMED.match(s[f]) for f in ("licence", "attribution")):
        return "licence"
    if s["kind"] == "document":
        if not TRIMMED.match(s["position"]) or not {"url", "fragment_sha256", "licence", "attribution"} <= set(s):
            return "document"
        if "revision" in s and not TRIMMED.match(s["revision"]):
            return "document"
        if "revision" not in s and "retrieved_at" not in s:
            return "document"
    if s.get("ownership") == "third_party" and not {"licence", "attribution"} <= set(s):
        return "third_party"
    return ""


def check_role_sources(data: bytes, bundle, snapshots: dict) -> list[dict]:
    """The findings for one role, sorted; none when its source entries are as they should be."""
    findings: list[dict] = []

    def finding(reason: str, **where) -> None:
        findings.append({"reason": reason, "severity": "error", **where})

    try:
        facts = tables(bundle)
        rows = {(t, k) for t in sorted(facts & set(snapshots)) for k in read_rows(snapshots[t], "json")}
        entries = json.loads(data)
    except (ValueError, KeyError, TypeError):
        return [{"reason": "sources_unreadable", "severity": "error"}]
    if not isinstance(entries, list):
        return [{"reason": "sources_unreadable", "severity": "error"}]
    seen, last = set(), None
    for e in entries:
        row = e.get("row") if isinstance(e, dict) else None
        if (not isinstance(row, dict) or set(e) - {"row", "sources", "reason"} or set(row) != {"relation", "key"}
                or not all(isinstance(v, str) for v in row.values())):
            finding("source_entry_shape")
            continue
        ref = (row["relation"], row["key"])
        if ref not in rows:
            finding("source_row_not_read")  # no relation or key: the role may not know the row exists
            continue
        where = {"relation": ref[0], "key": ref[1]}
        order = (utf16(ref[0]), utf16(ref[1]))
        if ref in seen or (last is not None and order <= last):
            finding("source_order", **where)
        seen.add(ref)
        last = order if last is None else max(last, order)
        if "reason" in e and (not isinstance(e["reason"], str) or not e["reason"].strip()):
            finding("source_entry_shape", **where)
        sources = e.get("sources")
        if not isinstance(sources, list) or not sources:
            finding("source_empty", **where)
            continue
        problems = sorted({p for p in map(source_problem, sources) if p})
        for p in problems:
            finding("source_fields", field=p, **where)
        if problems:
            continue
        texts = [canonical_json(s) for s in sources]
        if texts != sorted(set(texts), key=utf16):
            finding("source_order", **where)
    for rel, key in sorted(rows - seen):
        finding("source_missing", relation=rel, key=key)
    return sorted({canonical_json(f): f for f in findings}.values(), key=canonical_json)


def check_source_sets(sets: list, roles, read_object) -> list[dict]:
    """The manifest's `fact_sources` against the roles it publishes: one SourceSet per role, no other, each
    naming an object with exactly the bytes its hash says. Whether the bytes are right for the role is
    `check_role_sources`, on that role's own snapshots."""
    findings: list[dict] = []
    roles = set(roles)
    named = [s.get("role") if isinstance(s, dict) else None for s in sets]
    for s in sets:
        if not isinstance(s, dict) or set(s) != {"role", "uri", "sha256"} or not all(isinstance(v, str) for v in s.values()):
            findings.append({"reason": "source_set_shape", "severity": "error"})
            continue
        if s["role"] not in roles:
            findings.append({"reason": "source_set_role", "severity": "error"})
            continue
        if named.count(s["role"]) > 1:
            findings.append({"reason": "source_set_twice", "severity": "error", "role": s["role"]})
        data = read_object(s["uri"])
        if data is None or not SHA256.match(s["sha256"]) or hashlib.sha256(data).hexdigest() != s["sha256"]:
            findings.append({"reason": "source_set_hash", "severity": "error", "role": s["role"]})
    for role in sorted(roles - set(named)):
        findings.append({"reason": "source_set_missing", "severity": "error", "role": role})
    return sorted({canonical_json(f): f for f in findings}.values(), key=canonical_json)
