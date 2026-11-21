"""Thin coordinator reader over checker-verified build pack publications.

Reads published task-state and claim-release relations without making any
scheduling, ordering or lease-expiry decisions. Never accepts or invokes a
Python fallback: any missing, rejected or failed publication enters fail-closed
safe mode (claims stay intact, zero new tasks assigned, structured finding emitted).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_REQUIRED_CHECKS = frozenset({"rezono:proofs", "rezono:schema"})
_REQUIRED_RELATIONS = {
    "build_task_ready": 3,
    "build_task_waiting": 4,
    "build_task_stuck": 3,
    "build_claim_release_plan": 4,
    "build_claim_held": 3,
}


def _verified_manifest(manifest: Mapping[str, Any]) -> bool:
    """Return whether rezono:proofs and rezono:schema are green with no non-green checks."""
    checks = manifest.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        return False
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping) or check.get("status") != "green":
            return False
        name = check.get("name")
        if isinstance(name, str) and name:
            seen.add(name)
    return _REQUIRED_CHECKS <= seen


def _row_key(row: object, size: int, run: str) -> tuple[str, ...]:
    """Extract a validated publication row key for ``run`` or raise ``ValueError``."""
    key = row.get("key") if isinstance(row, Mapping) else None
    if not isinstance(key, (list, tuple)) or len(key) != size:
        raise ValueError(f"malformed publication row: {row!r}")
    if not all(isinstance(part, str) and part for part in key):
        raise ValueError(f"malformed publication row: {row!r}")
    if key[0] != run:
        raise ValueError(f"publication row belongs to another run: {key[0]!r}")
    return tuple(key)


def _safe_mode(run: str, reason: str) -> dict[str, Any]:
    return {
        "run": run,
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": reason,
        "assign_new_tasks": False,
        "ready": [],
        "waiting": [],
        "stuck": [],
        "claim_release_plan": [],
        "claim_held": [],
        "findings": [{
            "kind": "safe_mode",
            "run": run,
            "surface": "coordinator",
            "reason": reason,
        }],
    }


def read_coordinator_state(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    engine_error: str | None,
) -> dict[str, Any]:
    """Project verified task and claim-release relations for the coordinator.

    On engine error, missing publication, or checker-rejected / incomplete publication,
    enter fail-closed safe mode: claims stay intact, no new tasks are assigned, and a
    structured ``safe_mode`` finding is emitted.
    """
    if not isinstance(run, str) or not run:
        raise ValueError(f"run must be a non-empty string, got {run!r}")

    if engine_error:
        return _safe_mode(run, "engine-failure")
    if manifest is None or rows is None:
        return _safe_mode(run, "missing-publication")
    if not isinstance(manifest, Mapping) or not _verified_manifest(manifest):
        return _safe_mode(run, "invalid-publication")
    if not isinstance(rows, Mapping) or any(
        not isinstance(rows.get(name), Sequence) or isinstance(rows.get(name), (str, bytes))
        for name in _REQUIRED_RELATIONS
    ):
        return _safe_mode(run, "invalid-publication")

    ready = sorted({_row_key(row, 3, run) for row in rows["build_task_ready"]})
    waiting = sorted({_row_key(row, 4, run) for row in rows["build_task_waiting"]})
    stuck = sorted({_row_key(row, 3, run) for row in rows["build_task_stuck"]})
    release_plan = sorted({_row_key(row, 4, run) for row in rows["build_claim_release_plan"]})
    claim_held = sorted({_row_key(row, 3, run) for row in rows["build_claim_held"]})

    return {
        "run": run,
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "assign_new_tasks": True,
        "ready": [{"task": task, "reason": reason} for _, task, reason in ready],
        "waiting": [{"task": task, "token": token, "reason": reason} for _, task, token, reason in waiting],
        "stuck": [{"task": task, "reason": reason} for _, task, reason in stuck],
        "claim_release_plan": [
            {"claim": claim, "generation": generation, "reason": reason}
            for _, claim, generation, reason in release_plan
        ],
        "claim_held": [{"claim": claim, "reason": reason} for _, claim, reason in claim_held],
        "findings": [],
    }
