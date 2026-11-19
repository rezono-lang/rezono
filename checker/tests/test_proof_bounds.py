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


@pytest.mark.xfail(
    strict=True,
    raises=MissingProofBounds,
    reason=(
        "extra: decisions/central-read-access.md: Define MAX_PIECE = 65536, MAX_FANOUT = 128 and "
        "MAX_LEVELS = 8 in checker/rezono_checker/proof.py and enforce them in _Walk (check_proof, "
        "check_rows, check_indexes, check_sources, check_difference) so any caller-supplied limit above "
        "MAX_PIECE, fanout above MAX_FANOUT, or tree root with levels above MAX_LEVELS is refused."
    ),
)
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
