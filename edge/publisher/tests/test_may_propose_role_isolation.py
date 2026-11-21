"""Strict red tests for role-scoped `may_propose` isolation and self-grant delivery.

Covers decisions/reader-served-seal-fields.md section 2 (`may_propose` on `GET /<pack>/head`):
1. Cross-role isolation: a filtered role's published `may_propose` snapshot and witness set
   must contain ONLY rows for that target role — never another role's `may_propose` rows,
   even when the target role can read every premise of the rule that derived them.
2. Positive self-grant without `may_read(r, "role", r)`: a filtered role holding the
   `propose` capability must still receive its own `may_propose(role, kind, element)` rows
   (and `GET /<pack>/head` must serve `may_propose: true`) even when the role does not have
   `may_read(role, "role", role)`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_compiler import modules
from rezono_publisher import access, batch, publish, store

ROOT = Path(__file__).resolve().parents[3]
SLIP_FIXTURE = ROOT / "tests" / "fixtures" / "slip"
SLIP_READER = ROOT / "tests" / "slip" / "reader.mjs"
SLIP_ROLES = {"checker": "complete", "reader": "may_read", "summary": "may_read"}
KNOWLEDGE_TIME = "2026-01-01T00:00:00Z"


def _node_ts_cmd() -> list[str]:
    node = os.environ.get("REZONO_NODE", "node")
    version = subprocess.check_output([node, "-p", "process.versions.node"], text=True).strip()
    major = int(version.split(".", 1)[0])
    return [node, "--experimental-strip-types", "--no-warnings"] if major < 24 else [node]


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


def _witness(relation: str, key: list[str], rule_id: str, bindings: list[dict], premises: list[tuple[str, list[str]]]) -> dict:
    return {
        "conclusion": {"relation": relation, "key": canonical_json(key)},
        "rule_id": rule_id,
        "bindings": bindings,
        "premises": [
            {"polarity": "positive", "row": {"relation": prel, "key": canonical_json(pkey)}}
            for prel, pkey in premises
        ],
    }


def _ask_head(store_dir: Path, role: str) -> dict:
    run = subprocess.run(
        [*_node_ts_cmd(), str(SLIP_READER)],
        input=json.dumps({"store": store_dir.as_posix(), "role": role, "requests": ["/slip/head"]}),
        capture_output=True,
        encoding="utf-8",
        timeout=120,
        cwd=ROOT,
        check=False,
    )
    assert run.returncode == 0, run.stderr
    [answer] = json.loads(run.stdout)
    assert answer["status"] == 200, answer
    return answer["body"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/reader-served-seal-fields.md: section 2; access.for_role must strictly filter "
        "may_propose rows and witnesses to the target role so other roles' proposal grants never leak "
        "across roles even when all rule premises are readable."
    ),
)
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/reader-served-seal-fields.md: section 2; a filtered role holding propose capability "
        "must receive its own may_propose rows (and GET /<pack>/head must serve may_propose: true) even "
        "when that role does not have may_read(role, 'role', role)."
    ),
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
    readable, sees, _ = access.for_role(rows, kinds, {}, columns, rules, witnesses, "summary")
    assert readable.get("may_propose") == [("summary", "item", "item-a")], (
        f"summary must receive its own may_propose grant without may_read(summary, role, summary); "
        f"got {readable.get('may_propose')!r}"
    )
    propose_witnesses = [
        w for w in sees["witnesses"] if w["conclusion"]["relation"] == "may_propose"
    ]
    assert [w["conclusion"]["key"] for w in propose_witnesses] == [canonical_json(["summary", "item", "item-a"])]

    # 2. End-to-end publication + local reader GET /slip/head on tests/fixtures/slip:
    #    grant `propose` to `summary` only (summary still lacks `read_restricted`, so it cannot read `role`).
    pack_dir = modules.copy_closure(SLIP_FIXTURE, tmp_path / "closure")
    rows_path = pack_dir / "facts" / "rows.yaml"
    fact_rows = yaml.safe_load(rows_path.read_text(encoding="utf-8"))
    for role_row in fact_rows["role"]:
        if role_row["id"] == "summary":
            role_row["capability"] = [*role_row["capability"], "propose"]
    rows_path.write_text(yaml.safe_dump(fact_rows, sort_keys=False), encoding="utf-8", newline="\n")

    access_path = pack_dir / "rules" / "access.dl"
    access_path.write_text(
        access_path.read_text(encoding="utf-8")
        + '\n.decl may_propose(role: symbol, kind: symbol, element: symbol)\n'
        + 'may_propose(r, "item", i) :- role__capability(r, "propose"), item(i).\n',
        encoding="utf-8",
        newline="\n",
    )

    epoch = batch.epoch(pack_dir, epoch=1, knowledge_time=KNOWLEDGE_TIME, sources=[("rules", "test")])
    target = tmp_path / "store"
    manifest = publish.publish(epoch, store.FileStore(target), SLIP_ROLES)

    summary_snap = next(
        s for s in manifest["snapshots"] if s["role"] == "summary" and s["relation"] == "may_propose"
    )
    summary_snap_rows = json.loads((target / "slip" / "objects" / f"{summary_snap['sha256']}.json").read_bytes())
    assert {"key": ["summary", "item", "item-a"]} in summary_snap_rows
    assert all(entry["key"][0] == "summary" for entry in summary_snap_rows)

    reader_snap = next(
        s for s in manifest["snapshots"] if s["role"] == "reader" and s["relation"] == "may_propose"
    )
    reader_snap_rows = json.loads((target / "slip" / "objects" / f"{reader_snap['sha256']}.json").read_bytes())
    assert reader_snap_rows == []

    assert _ask_head(target, "summary")["may_propose"] is True
    assert _ask_head(target, "reader")["may_propose"] is False
