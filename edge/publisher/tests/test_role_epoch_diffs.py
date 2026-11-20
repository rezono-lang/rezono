"""Role-scoped epoch diffs and chained epoch statements (decisions/publication-role-diffs.md).

Publishes three consecutive main epochs (`m-1`, `m-2`, `m-3`) for two filtered roles (`role_a` and `role_b`),
where epochs 2 and 3 change only rows readable by `role_a`. Role `role_b`'s diff must be empty and its epoch
statement must change only in epoch-chain fields — never in snapshot hashes, dataset/root hashes, or diff contents.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler" / "tests" / "fixtures" / "minimal"
ROLES = {"checker": "complete", "role_a": "may_read", "role_b": "may_read"}
RULES = """.decl may_read(role: symbol, kind: symbol, element: symbol)
may_read("role_a", "alpha", x) :- alpha__title(x, "only_a").
may_read("role_b", "alpha", x) :- alpha__title(x, "only_b").
"""
TOOL_SIDECAR = {"default": {"kind": "tool", "name": "Epoch generator", "position": "run 1"}}
EMPTY_DIFF_BYTES = b'{"format":"rezono.role-diff/1","relations":{}}'
EMPTY_DIFF_SHA256 = hashlib.sha256(EMPTY_DIFF_BYTES).hexdigest()
INITIAL_TO_CHAINED_FIELDS = frozenset({"manifest", "epoch", "knowledge_time", "role_manifest", "previous", "diff"})
CHAINED_ONLY_FIELDS = frozenset({"manifest", "epoch", "knowledge_time", "role_manifest", "previous"})


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_pack(directory: Path, alphas: list[dict]) -> Path:
    shutil.copytree(MINIMAL, directory)
    (directory / "facts").mkdir()
    (directory / "facts" / "a.yaml").write_text(
        yaml.safe_dump({"alpha": alphas}, sort_keys=False), encoding="utf-8", newline="\n"
    )
    (directory / "facts" / "a.sources.yaml").write_text(
        yaml.safe_dump(TOOL_SIDECAR, sort_keys=True), encoding="utf-8", newline="\n"
    )
    (directory / "rules").mkdir()
    (directory / "rules" / "access.dl").write_text(RULES, encoding="utf-8", newline="\n")
    return directory


def _publish_epoch(st: store.FileStore, pack_dir: Path, *, epoch_num: int, knowledge_time: str) -> dict:
    ep = batch.epoch(pack_dir, epoch=epoch_num, knowledge_time=knowledge_time, sources=[("rules", f"e{epoch_num}")])
    return publish.publish(ep, st, ROLES, None, forms=True)


def _read_role_publication(st: store.FileStore, manifest_id: str, role: str) -> tuple[dict, bytes, dict, bytes | None]:
    prefix = f"minimal/{manifest_id}/{role}/publication/"
    index_bytes = st.get(prefix + "index.json")
    assert index_bytes is not None, f"missing {prefix}index.json"
    stmt_bytes = st.get(prefix + "statement.json")
    assert stmt_bytes is not None, f"missing {prefix}statement.json"
    diff_bytes = st.get(prefix + "diff.json")
    return json.loads(index_bytes), stmt_bytes, json.loads(stmt_bytes), diff_bytes


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/publication-role-diffs.md: Compute role-scoped epoch diffs strictly from each filtered "
        "role's own previous and current snapshots (`diff.json`, format `rezono.role-diff/1`), verify them with "
        "`rezono_checker.difference.changes`, and emit epoch statement v2 (`contracts/statement.yaml`, "
        "`publication/rezono_publication/statement.py`, `edge/publisher/rezono_publisher/forms.py`) recording "
        "`previous` (prior role statement sha256) and `diff` (role diff sha256)."
    ),
)
def test_role_epoch_diff_is_empty_and_statement_changes_only_chain_fields_on_other_role_change(tmp_path: Path):
    st = store.FileStore(tmp_path / "store")

    # Epoch 1: role_a sees a1, role_b sees b1.
    p1 = _make_pack(
        tmp_path / "e1",
        [
            {"id": "a1", "title": "only_a", "size": 1},
            {"id": "b1", "title": "only_b", "size": 2},
        ],
    )
    _publish_epoch(st, p1, epoch_num=1, knowledge_time="2026-01-01T00:00:00Z")

    # Epoch 2: changes readable ONLY by role_a (a1 updated, a2 added); role_b's readable state is untouched.
    p2 = _make_pack(
        tmp_path / "e2",
        [
            {"id": "a1", "title": "only_a", "size": 4},
            {"id": "a2", "title": "only_a", "size": 5},
            {"id": "b1", "title": "only_b", "size": 2},
        ],
    )
    _publish_epoch(st, p2, epoch_num=2, knowledge_time="2026-01-02T00:00:00Z")

    # Epoch 3: another change readable ONLY by role_a (a2 updated); role_b remains untouched.
    p3 = _make_pack(
        tmp_path / "e3",
        [
            {"id": "a1", "title": "only_a", "size": 4},
            {"id": "a2", "title": "only_a", "size": 6},
            {"id": "b1", "title": "only_b", "size": 2},
        ],
    )
    _publish_epoch(st, p3, epoch_num=3, knowledge_time="2026-01-03T00:00:00Z")

    # Read published forms for role_a and role_b across all three epochs.
    _, a1_stmt_bytes, a1_stmt, a1_diff = _read_role_publication(st, "m-1", "role_a")
    a2_idx, _, a2_stmt, a2_diff = _read_role_publication(st, "m-2", "role_a")

    _, b1_stmt_bytes, b1_stmt, b1_diff = _read_role_publication(st, "m-1", "role_b")
    b2_idx, b2_stmt_bytes, b2_stmt, b2_diff = _read_role_publication(st, "m-2", "role_b")
    b3_idx, _, b3_stmt, b3_diff = _read_role_publication(st, "m-3", "role_b")

    # Version 2 epoch statements everywhere; initial epoch has no previous, no diff, and no diff.json.
    for stmt in (a1_stmt, a2_stmt, b1_stmt, b2_stmt, b3_stmt):
        assert stmt["predicateType"] == "https://rezono.org/epoch-statement/v2", stmt["predicateType"]
        assert stmt["predicate"]["format"] == "rezono.epoch-statement/2", stmt["predicate"]["format"]
    assert a1_diff is None and b1_diff is None
    assert "previous" not in a1_stmt["predicate"] and "diff" not in a1_stmt["predicate"]
    assert "previous" not in b1_stmt["predicate"] and "diff" not in b1_stmt["predicate"]

    # Role A's diff in m-2 captures only role A's snapshot changes and links to role A's m-1 statement.
    assert a2_diff is not None, "role_a must have diff.json on chained epoch m-2"
    a2_diff_doc = json.loads(a2_diff)
    assert a2_diff_doc["format"] == "rezono.role-diff/1"
    assert a2_diff_doc["relations"]["alpha"] == [{"change": "added", "key": ["a2"]}]
    assert a2_diff_doc["relations"]["alpha__size"] == [
        {"change": "changed", "key": ["a1", "4"], "was": ["a1", "1"]},
        {"change": "added", "key": ["a2", "5"]},
    ]
    assert a2_diff_doc["relations"]["alpha__title"] == [{"change": "added", "key": ["a2", "only_a"]}]
    assert b"b1" not in a2_diff and b"only_b" not in a2_diff
    assert a2_stmt["predicate"]["previous"] == _sha256(a1_stmt_bytes)
    assert a2_stmt["predicate"]["diff"] == _sha256(a2_diff)
    assert any(obj["name"] == "diff.json" and obj["sha256"] == _sha256(a2_diff) for obj in a2_idx["objects"])

    # Role B's diffs in m-2 and m-3 are canonically empty and carry zero role A content.
    assert b2_diff == EMPTY_DIFF_BYTES, f"expected empty role_b diff in m-2, got {b2_diff!r}"
    assert b3_diff == EMPTY_DIFF_BYTES, f"expected empty role_b diff in m-3, got {b3_diff!r}"
    assert any(obj["name"] == "diff.json" and obj["sha256"] == EMPTY_DIFF_SHA256 for obj in b2_idx["objects"])
    assert any(obj["name"] == "diff.json" and obj["sha256"] == EMPTY_DIFF_SHA256 for obj in b3_idx["objects"])

    # Role B's statements chain to role B's own prior statements and record the empty diff hash.
    b1_pred, b2_pred, b3_pred = b1_stmt["predicate"], b2_stmt["predicate"], b3_stmt["predicate"]
    assert b2_pred["previous"] == _sha256(b1_stmt_bytes)
    assert b2_pred["diff"] == EMPTY_DIFF_SHA256
    assert b3_pred["previous"] == _sha256(b2_stmt_bytes)
    assert b3_pred["diff"] == EMPTY_DIFF_SHA256

    # m-1 -> m-2: role B's statement changes ONLY in epoch-chain fields; snapshots, hashes, and data subjects stay identical.
    changed_1_to_2 = {k for k in set(b1_pred) | set(b2_pred) if b1_pred.get(k) != b2_pred.get(k)}
    assert changed_1_to_2 <= INITIAL_TO_CHAINED_FIELDS, f"non-chain predicate fields changed: {changed_1_to_2}"
    assert b1_pred["snapshots"] == b2_pred["snapshots"]
    assert b1_pred["dataset"] == b2_pred["dataset"]
    assert b1_pred["annotation"] == b2_pred["annotation"]
    assert b1_pred["roots"] == b2_pred["roots"]
    assert b1_pred["inclusion"] == b2_pred["inclusion"]

    b1_subjects = {s["name"]: s["digest"]["sha256"] for s in b1_stmt["subject"]}
    b2_subjects = {s["name"]: s["digest"]["sha256"] for s in b2_stmt["subject"]}
    assert b2_subjects == {**b1_subjects, "diff.json": EMPTY_DIFF_SHA256}

    # m-2 -> m-3: even diff.json and predicate.diff stay identical; ONLY epoch-chain fields advance.
    changed_2_to_3 = {k for k in set(b2_pred) | set(b3_pred) if b2_pred.get(k) != b3_pred.get(k)}
    assert changed_2_to_3 <= CHAINED_ONLY_FIELDS, f"non-chain predicate fields changed: {changed_2_to_3}"
    assert b2_pred["snapshots"] == b3_pred["snapshots"]
    assert b2_pred["diff"] == b3_pred["diff"] == EMPTY_DIFF_SHA256
    assert b2_stmt["subject"] == b3_stmt["subject"]
