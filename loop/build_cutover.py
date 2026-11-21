"""Thin CI suite-selection reader over checker-verified build pack publications.

Never accepts or invokes a Python fallback selector: any missing, rejected or
failed publication enters fail-closed safe mode selecting every suite in the
universe and emitting a structured ``safe_mode`` finding.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from loop.build_selection_outcome import resolve_selection


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

    failure, suites, full_reasons = resolve_selection(
        run=run, manifest=manifest, rows=rows, engine_error=engine_error
    )
    if failure is not None:
        return _safe_mode(run, failure, all_suites)

    return {
        "run": run,
        "source": "pack",
        "safe_mode": False,
        "safe_mode_reason": None,
        "use": list(all_suites) if full_reasons else suites,
        "findings": [],
    }
