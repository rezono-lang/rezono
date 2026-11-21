"""Strict red tests for role-scoped `may_propose` isolation and self-grant delivery.

Covers decisions/reader-served-seal-fields.md section 2 (`may_propose` on `GET /<pack>/head`):
1. Cross-role isolation: a filtered role's published `may_propose` snapshot and witness set
   must contain ONLY rows for that target role — never another role's `may_propose` rows,
   even when the target role can read every premise of the rule that derived them.
2. Positive self-grant without `may_read(r, "role", r)`: a filtered role holding the
   `propose` capability must still receive its own `may_propose(role, kind, element)` rows
   in its published role-scoped `may_propose` slice even when the role does not have
   `may_read(role, "role", role)`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_publisher import access, batch, publish, store

ROLES = {"checker": "complete", "reader": "may_read", "summary": "may_read"}
KNOWLEDGE_TIME = "2026-01-01T00:00:00Z"


def _lit(rel: str, *terms: str) -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": "positive", "stratum": 0}


def _rule(rid: str, head: tuple[str, ...], body: list[dict]) -> dict:
    return {
        "id": rid,
        "stratum": 0,
        "head": {"relation": head[0], "terms": list(head[1:])},
        "body": body,
    }


def _relation(name: str, role: str, arity: int) -> dict:
    return {"name": name, "role": role, "key": [{"name": f"c{i}", "type": "string"} for i in range(arity)]}


def _witness(
    relation: str,
    key: list[str],
    rule_id: str,
    bindings: list[dict],
    premises: list[tuple[str, list[str]]],
) -> dict:
    return {
        "conclusion": {"relation": relation, "key": canonical_json(key)},
        "rule_id": rule_id,
        "bindings": bindings,
        "premises": [
            {"polarity": "positive", "row": {"relation": prel, "key": canonical_json(pkey)}}
            for prel, pkey in premises
        ],
    }


def _write_self_contained_propose_pack(pack_dir: Path) -> Path:
    """Create a self-contained mini-pack in `pack_dir` where `summary` holds `[read, propose]` without reading `role`."""
    for sub in ("schema", "rules", "facts", "labels", "messages"):
        (pack_dir / sub).mkdir(parents=True, exist_ok=True)

    (pack_dir / "pack.yaml").write_text(
        yaml.safe_dump(
            {
                "name": "mini-propose",
                "version": "0.1.0",
                "default_language": "en",
                "imports": [],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "channels.yaml").write_text(
        "kinds:\n  - {kind: item, shape: pill}\n  - {kind: role, shape: pill}\n",
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "schema" / "mini.yaml").write_text(
        """\
id: https://rezono.example/mini-propose/schema
name: mini_propose
prefixes:
  linkml: https://w3id.org/linkml/
imports:
  - linkml:types
default_range: string
annotations:
  layer: facts
enums:
  Capability:
    annotations:
      world: closed
    permissible_values:
      read: {}
      propose: {}
      read_restricted: {}
classes:
  Role:
    annotations:
      world: closed
    attributes:
      id:
        identifier: true
        required: true
      title:
        required: true
      capability:
        range: Capability
        multivalued: true
  Item:
    annotations:
      world: closed
    attributes:
      id:
        identifier: true
        required: true
      title:
        required: true
""",
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "rules" / "access.dl").write_text(
        """\
.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read(r, "item", i) :- role__capability(r, "read"), item(i).
may_read(r, "role", x) :- role__capability(r, "read_restricted"), role(x).

.decl may_read_full(role: symbol, kind: symbol)
may_read_full(r, "item") :- role__capability(r, "read").
may_read_full(r, "role") :- role__capability(r, "read_restricted").

.decl may_propose(role: symbol, kind: symbol, element: symbol)
may_propose(r, "item", i) :- role__capability(r, "propose"), item(i).
""",
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "facts" / "rows.yaml").write_text(
        yaml.safe_dump(
            {
                "role": [
                    {"id": "reader", "title": "Reader", "capability": ["read", "read_restricted"]},
                    {"id": "summary", "title": "Summary", "capability": ["read", "propose"]},
                ],
                "item": [
                    {"id": "item-a", "title": "Item A"},
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "facts" / "rows.sources.yaml").write_text(
        yaml.safe_dump(
            {
                "default": {
                    "kind": "synthetic",
                    "name": "mini-propose-test",
                    "revision": "1",
                    "position": "facts/rows.yaml",
                }
            },
            sort_keys=False,
        ),
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "labels" / "en.yaml").write_text(
        "item: item\n"
        "item.title: title\n"
        "role: role\n"
        "role.title: title\n"
        "role.capability: capability\n",
        encoding="utf-8",
        newline="\n",
    )
    (pack_dir / "messages" / "en.mf2").write_text(
        "@locale en\n---\n"
        "arrow.total = {{Every {$kind} has exactly one {$arrow}.}}\n"
        "arrow.partial = {{Every {$kind} has at most one {$arrow}.}}\n"
        "attribute.total = {{Every {$kind} has exactly one {$attribute}.}}\n"
        "attribute.partial = {{Every {$kind} has at most one {$attribute}.}}\n"
        "attribute.many.total = {{Every {$kind} has at least one {$attribute}.}}\n"
        "attribute.many.partial = {{Every {$kind} may have {$attribute} values.}}\n"
        "is_a = {{Every {$kind} is a {$parent}.}}\n"
        "unique_key = {{{$key} belongs to at most one {$kind}.}}\n"
        "path_equation = {{For every {$kind}: {$equation}.}}\n",
        encoding="utf-8",
        newline="\n",
    )
    return pack_dir


def test_may_propose_never_leaks_other_roles_rows_or_witnesses():
    kinds = {"item", "role"}
    columns = {
        "item": ("item",),
        "role": ("role",),
        "role__capability": ("role", None),
    }
    rules = {
        "format": "rezono.rules/1",
        "relations": [
            _relation("item", "base", 1),
            _relation("role", "base", 1),
            _relation("role__capability", "base", 2),
            _relation("may_read", "derived", 3),
            _relation("may_propose", "derived", 3),
        ],
        "rules": [
            _rule(
                "read_items",
                ("may_read", "?r", "item", "?i"),
                [_lit("role__capability", "?r", "read"), _lit("item", "?i")],
            ),
            _rule(
                "read_roles",
                ("may_read", "?r", "role", "?x"),
                [_lit("role__capability", "?r", "read_restricted"), _lit("role", "?x")],
            ),
            # Constant target role: summary can read the only premise `item(i)`.
            _rule(
                "propose_reader_const",
                ("may_propose", "reader", "item", "?i"),
                [_lit("item", "?i")],
            ),
            # Capability rule: reader can read `role` and `role__capability`, so reader can read summary's premises.
            _rule(
                "propose_by_cap",
                ("may_propose", "?r", "item", "?i"),
                [_lit("role__capability", "?r", "propose"), _lit("item", "?i")],
            ),
        ],
    }

    # Case 1: summary has NO propose grant; constant rule grants ("reader", "item", "item-a") using only `item`.
    rows_const = {
        "item": [("item-a",)],
        "role": [("reader",), ("summary",)],
        "role__capability": [("reader", "read"), ("reader", "read_restricted"), ("summary", "read")],
        "may_read": [
            ("reader", "item", "item-a"),
            ("reader", "role", "reader"),
            ("reader", "role", "summary"),
            ("summary", "item", "item-a"),
        ],
        "may_propose": [("reader", "item", "item-a")],
    }
    witnesses_const = [
        _witness(
            "may_propose",
            ["reader", "item", "item-a"],
            "propose_reader_const",
            [{"variable": "?i", "value": "item-a"}],
            [("item", ["item-a"])],
        ),
    ]
    summary_readable, summary_sees, _ = access.for_role(
        rows_const, kinds, {}, columns, rules, witnesses_const, "summary"
    )
    assert summary_readable.get("may_propose", []) == [], (
        f"summary must never receive reader's may_propose rows: {summary_readable.get('may_propose')!r}"
    )
    summary_propose_witnesses = [
        w for w in summary_sees["witnesses"] if w["conclusion"]["relation"] == "may_propose"
    ]
    assert summary_propose_witnesses == [], (
        f"summary must never receive reader's may_propose witnesses: {summary_propose_witnesses!r}"
    )

    # Case 2: summary holds `propose`, reader holds `read_restricted` (can read `role` and `role__capability`),
    # but reader does NOT hold `propose` -> reader must never see summary's may_propose row or witness.
    rows_cap = {
        "item": [("item-a",)],
        "role": [("reader",), ("summary",)],
        "role__capability": [
            ("reader", "read"),
            ("reader", "read_restricted"),
            ("summary", "read"),
            ("summary", "propose"),
        ],
        "may_read": [
            ("reader", "item", "item-a"),
            ("reader", "role", "reader"),
            ("reader", "role", "summary"),
            ("summary", "item", "item-a"),
        ],
        "may_propose": [("summary", "item", "item-a")],
    }
    witnesses_cap = [
        _witness(
            "may_propose",
            ["summary", "item", "item-a"],
            "propose_by_cap",
            [{"variable": "?r", "value": "summary"}, {"variable": "?i", "value": "item-a"}],
            [("role__capability", ["summary", "propose"]), ("item", ["item-a"])],
        ),
    ]
    reader_readable, reader_sees, _ = access.for_role(
        rows_cap, kinds, {}, columns, rules, witnesses_cap, "reader"
    )
    assert reader_readable.get("may_propose", []) == [], (
        f"reader must never receive summary's may_propose rows: {reader_readable.get('may_propose')!r}"
    )
    reader_propose_witnesses = [
        w for w in reader_sees["witnesses"] if w["conclusion"]["relation"] == "may_propose"
    ]
    assert reader_propose_witnesses == [], (
        f"reader must never receive summary's may_propose witnesses: {reader_propose_witnesses!r}"
    )


def test_may_propose_self_grant_delivered_without_reading_role_kind(tmp_path: Path):
    # 1. Direct publisher access filter check: summary has capability [read, propose] and reads item-a,
    #    but has NO may_read("summary", "role", "summary").
    kinds = {"item", "role"}
    columns = {
        "item": ("item",),
        "role": ("role",),
        "role__capability": ("role", None),
    }
    rules = {
        "format": "rezono.rules/1",
        "relations": [
            _relation("item", "base", 1),
            _relation("role", "base", 1),
            _relation("role__capability", "base", 2),
            _relation("may_read", "derived", 3),
            _relation("may_propose", "derived", 3),
        ],
        "rules": [
            _rule(
                "read_items",
                ("may_read", "?r", "item", "?i"),
                [_lit("role__capability", "?r", "read"), _lit("item", "?i")],
            ),
            _rule(
                "read_roles",
                ("may_read", "?r", "role", "?x"),
                [_lit("role__capability", "?r", "read_restricted"), _lit("role", "?x")],
            ),
            _rule(
                "propose_by_cap",
                ("may_propose", "?r", "item", "?i"),
                [_lit("role__capability", "?r", "propose"), _lit("item", "?i")],
            ),
        ],
    }
    rows = {
        "item": [("item-a",)],
        "role": [("reader",), ("summary",)],
        "role__capability": [
            ("reader", "read"),
            ("reader", "read_restricted"),
            ("summary", "read"),
            ("summary", "propose"),
        ],
        "may_read": [
            ("reader", "item", "item-a"),
            ("reader", "role", "reader"),
            ("reader", "role", "summary"),
            ("summary", "item", "item-a"),
        ],
        "may_propose": [("summary", "item", "item-a")],
    }
    witnesses = [
        _witness(
            "may_propose",
            ["summary", "item", "item-a"],
            "propose_by_cap",
            [{"variable": "?r", "value": "summary"}, {"variable": "?i", "value": "item-a"}],
            [("role__capability", ["summary", "propose"]), ("item", ["item-a"])],
        ),
    ]
    readable, _, _ = access.for_role(rows, kinds, {}, columns, rules, witnesses, "summary")
    assert readable.get("may_propose") == [("summary", "item", "item-a")], (
        f"summary must receive its own may_propose grant without may_read(summary, role, summary); "
        f"got {readable.get('may_propose')!r}"
    )

    # 2. End-to-end publication on a self-contained mini-pack:
    #    summary holds `capability: [read, propose]` (no `read_restricted`, so no `may_read("summary", "role", "summary")`);
    #    reader holds `capability: [read, read_restricted]` (no `propose`).
    pack_dir = _write_self_contained_propose_pack(tmp_path / "mini-propose")
    epoch = batch.epoch(pack_dir, epoch=1, knowledge_time=KNOWLEDGE_TIME, sources=[("rules", "test")])
    target = tmp_path / "store"
    manifest = publish.publish(epoch, store.FileStore(target), ROLES)

    summary_snap = next(
        s for s in manifest["snapshots"] if s["role"] == "summary" and s["relation"] == "may_propose"
    )
    summary_snap_rows = json.loads((target / "mini-propose" / "objects" / f"{summary_snap['sha256']}.json").read_bytes())
    assert summary_snap_rows == [{"key": ["summary", "item", "item-a"]}], (
        f"summary's published may_propose snapshot must contain its own grant; got {summary_snap_rows!r}"
    )

    reader_snap = next(
        s for s in manifest["snapshots"] if s["role"] == "reader" and s["relation"] == "may_propose"
    )
    reader_snap_rows = json.loads((target / "mini-propose" / "objects" / f"{reader_snap['sha256']}.json").read_bytes())
    assert reader_snap_rows == [], (
        f"reader's published may_propose snapshot must remain empty; got {reader_snap_rows!r}"
    )
