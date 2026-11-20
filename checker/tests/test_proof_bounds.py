"""The checker enforces its own upper bounds on proof-index piece size, fanout and tree depth
(decisions/central-read-access.md, section 4)."""

from __future__ import annotations

import hashlib
import json

import pytest

from rezono_checker import difference, proof


class MissingProofBounds(AssertionError):
    """rezono_checker.proof does not yet define or enforce MAX_PIECE, MAX_FANOUT and MAX_LEVELS."""


def _leaf(tree: str, relation: str, rows: list) -> tuple[bytes, dict]:
    data = json.dumps(
        {"format": proof.FORMAT, "tree": tree, "relation": relation, "level": 0, "rows": rows},
        separators=(",", ":"),
    ).encode("utf-8")
    digest = hashlib.sha256(data).hexdigest()
    return data, {"file": f"{tree}/{relation}/0/0.json", "sha256": digest, "levels": 1}


def test_checker_refuses_proof_index_above_its_own_limits():
    max_piece = getattr(proof, "MAX_PIECE", None)
    max_fanout = getattr(proof, "MAX_FANOUT", None)
    max_levels = getattr(proof, "MAX_LEVELS", None)
    if (max_piece, max_fanout, max_levels) != (64 * 1024, 128, 8):
        raise MissingProofBounds(
            f"expected (MAX_PIECE, MAX_FANOUT, MAX_LEVELS) == (65536, 128, 8), got {(max_piece, max_fanout, max_levels)}"
        )

    rows = [{"key": ["a"]}]
    snap = json.dumps(rows).encode("utf-8")
    leaf_bytes, root = _leaf("rows", "item", rows)
    pieces = {root["file"]: leaf_bytes}
    row_roots = {"item": root | {"count": 1}}

    # Counter-case: at the checker's own bounds, the valid index passes.
    assert proof.check_rows({"item": snap}, pieces, row_roots, max_piece, max_fanout) == []

    # Caller-supplied limits above the checker's own bounds must be refused everywhere _Walk is used.
    assert proof.check_rows({"item": snap}, pieces, row_roots, max_piece + 1, max_fanout)
    assert proof.check_rows({"item": snap}, pieces, row_roots, max_piece, max_fanout + 1)
    assert proof.check_rows({"item": snap}, pieces, row_roots, 0, max_fanout)
    assert proof.check_rows({"item": snap}, pieces, row_roots, max_piece, 1)

    diff_rows = [{"key": ["a"], "change": "added"}]
    diff_bytes, diff_root = _leaf("difference", "item", diff_rows)
    assert difference.check_difference(
        {}, {"item": snap}, {diff_root["file"]: diff_bytes},
        {"item": {"added": 1, "removed": 0, "changed": 0}}, {"item": diff_root},
        max_piece, max_fanout,
    ) == []
    assert difference.check_difference(
        {}, {"item": snap}, {diff_root["file"]: diff_bytes},
        {"item": {"added": 1, "removed": 0, "changed": 0}}, {"item": diff_root},
        max_piece + 1, max_fanout,
    )

    # A root claiming levels above MAX_LEVELS must be refused even when limit and fanout are within bounds.
    deep_roots = {"item": root | {"count": 1, "levels": max_levels + 1}}
    assert proof.check_rows({"item": snap}, pieces, deep_roots, max_piece, max_fanout)


def test_invalid_limits_are_clamped_and_oversized_pieces_are_not_parsed():
    rows = [{"key": ["a"]}]
    snap = json.dumps(rows).encode("utf-8")
    leaf_bytes, leaf_root = _leaf("rows", "item", rows)
    page_obj = {
        "format": proof.FORMAT,
        "tree": "rows",
        "relation": "item",
        "level": 1,
        "children": [
            {"first": ["a"], "last": ["a"], "file": leaf_root["file"], "sha256": leaf_root["sha256"]},
        ],
    }
    page_bytes = json.dumps(page_obj, separators=(",", ":")).encode("utf-8")
    page_path = "rows/item/1/0.json"
    page_root = {"file": page_path, "sha256": hashlib.sha256(page_bytes).hexdigest(), "levels": 2, "count": 1}
    pieces = {leaf_root["file"]: leaf_bytes, page_path: page_bytes}

    # Non-int and bool limits/fanouts must report problems without raising TypeError.
    for bad_limit in (None, "65536", True):
        probs = proof.check_rows({"item": snap}, pieces, {"item": page_root}, bad_limit, proof.MAX_FANOUT)
        assert any("piece limit" in p for p in probs), (bad_limit, probs)
    for bad_fanout in (None, "128", False):
        probs = proof.check_rows({"item": snap}, pieces, {"item": page_root}, proof.MAX_PIECE, bad_fanout)
        assert any("fanout" in p for p in probs), (bad_fanout, probs)

    # An oversized caller limit is clamped to MAX_PIECE and oversized pieces are refused before json.loads.
    oversized_bytes = b"not-json" + b" " * proof.MAX_PIECE
    oversized_path = "rows/item/0/0.json"
    oversized_root = {
        "file": oversized_path,
        "sha256": hashlib.sha256(oversized_bytes).hexdigest(),
        "levels": 1,
        "count": 1,
    }
    probs = proof.check_rows(
        {"item": snap}, {oversized_path: oversized_bytes}, {"item": oversized_root},
        proof.MAX_PIECE + 1000, proof.MAX_FANOUT,
    )
    assert any("piece limit" in p for p in probs), probs
    assert any(f"more than {proof.MAX_PIECE}" in p for p in probs), probs

    # An oversized caller fanout is clamped to MAX_FANOUT and oversized pages are refused without walking children.
    wide_children = [
        {"first": ["a"], "last": ["a"], "file": f"rows/item/0/{i}.json", "sha256": "0" * 64}
        for i in range(proof.MAX_FANOUT + 1)
    ]
    wide_page = json.dumps(
        {"format": proof.FORMAT, "tree": "rows", "relation": "item", "level": 1, "children": wide_children},
        separators=(",", ":"),
    ).encode("utf-8")
    assert len(wide_page) <= proof.MAX_PIECE
    wide_root = {"file": page_path, "sha256": hashlib.sha256(wide_page).hexdigest(), "levels": 2, "count": 1}
    probs = proof.check_rows(
        {"item": snap}, {page_path: wide_page}, {"item": wide_root},
        proof.MAX_PIECE, proof.MAX_FANOUT + 10,
    )
    assert any("fanout" in p for p in probs), probs
    assert any(f"1 to {proof.MAX_FANOUT}" in p for p in probs), probs
    assert not any(": missing" in p for p in probs), probs
