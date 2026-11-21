"""Thin CI suite-selection reader over checker-verified build pack publications.

Never accepts or invokes a Python fallback selector: any missing, rejected or
failed publication enters fail-closed safe mode selecting every suite in the
universe and emitting a structured ``safe_mode`` finding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_REQUIRED_CHECKS = frozenset({"rezono:proofs", "rezono:schema"})
_REQUIRED_RELATIONS = {"build_selected_job": 3, "build_full_selection": 2}


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


def _safe_mode(run: str, reason: str, all_suites: list[str]) -> dict[str, Any]:
    return {
        "run": run,
        "source": "safe_mode",
        "safe_mode": True,
        "safe_mode_reason": reason,
        "use": list(all_suites),
        "findings": [{
            "kind": "safe_mode",
            "run": run,
            "surface": "ci_selection",
            "reason": reason,
        }],
    }


def select_suites(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    engine_error: str | None,
    universe: Iterable[str],
) -> dict[str, Any]:
    """Project verified ``build_selected_job`` / ``build_full_selection`` rows to CI suites.

    On engine error, missing publication, or checker-rejected / incomplete publication,
    enter fail-closed safe mode running every suite in ``universe``.
    """
    if not isinstance(run, str) or not run:
        raise ValueError(f"run must be a non-empty string, got {run!r}")
    all_suites = sorted(set(universe))

    if engine_error:
        return _safe_mode(run, "engine-failure", all_suites)
    if manifest is None or rows is None:
        return _safe_mode(run, "missing-publication", all_suites)
    if not isinstance(manifest, Mapping) or not _verified_manifest(manifest):
        return _safe_mode(run, "invalid-publication", all_suites)
    if not isinstance(rows, Mapping) or any(
        not isinstance(rows.get(name), Sequence) or isinstance(rows.get(name), (str, bytes))
        for name in _REQUIRED_RELATIONS
    ):
        return _safe_mode(run, "invalid-publication", all_suites)

    suites = {_row_key(row, 3, run)[1] for row in rows["build_selected_job"]}
    full_reasons = {_row_key(row, 2, run)[1] for row in rows["build_full_selection"]}

    return {
        "run": run,
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "use": list(all_suites) if full_reasons else sorted(suites),
        "findings": [],
    }
