"""Turn a build publication, or its absence, into a suite selection or full checks with the reason."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_REQUIRED_CHECKS = frozenset({"rezono:proofs", "rezono:schema"})
_RELATIONS = {"build_selected_job": 3, "build_full_selection": 2}


def _full(*reasons: str) -> dict[str, Any]:
    return {"mode": "full", "suites": [], "reasons": list(reasons)}


def verified_manifest(manifest: Mapping[str, Any]) -> bool:
    """Return whether rezono:proofs and rezono:schema are green with no non-green checks or violations."""
    checks = manifest.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        return False
    seen: set[str] = set()
    for check in checks:
        if not isinstance(check, Mapping) or check.get("status") != "green":
            return False
        violations = check.get("violations", 0)
        if type(violations) is not int or violations != 0:
            return False
        name = check.get("name")
        if isinstance(name, str) and name:
            seen.add(name)
    return _REQUIRED_CHECKS <= seen


def _key(row: object, size: int, run: str) -> tuple[str, ...]:
    """Return the row key as strings, or raise when it is malformed or belongs to another run."""
    key = row.get("key") if isinstance(row, Mapping) else None
    if not isinstance(key, (list, tuple)) or len(key) != size:
        raise ValueError(f"malformed publication row: {row!r}")
    if not all(isinstance(part, str) and part for part in key):
        raise ValueError(f"malformed publication row: {row!r}")
    if key[0] != run:
        raise ValueError(f"publication row of another run: {key[0]!r}")
    return tuple(key)


def resolve_selection(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    engine_error: str | None,
) -> tuple[str | None, list[str], list[str]]:
    """Evaluate the single strict publication-acceptance rule for build suite selection.

    Returns ``(failure_reason, suites, full_reasons)``. When ``failure_reason`` is not
    ``None``, publication acceptance failed (``engine-failure``, ``missing-publication`` or
    ``invalid-publication``). Otherwise the publication passed strict verification and
    ``suites`` / ``full_reasons`` hold the validated sorted pack rows.
    """
    if engine_error:
        return "engine-failure", [], []
    if manifest is None or rows is None:
        return "missing-publication", [], []
    if not isinstance(manifest, Mapping) or not verified_manifest(manifest):
        return "invalid-publication", [], []
    if not isinstance(rows, Mapping) or any(
        not isinstance(rows.get(name), Sequence) or isinstance(rows.get(name), (str, bytes)) for name in _RELATIONS
    ):
        return "invalid-publication", [], []
    suites = sorted({_key(row, 3, run)[1] for row in rows["build_selected_job"]})
    reasons = sorted({_key(row, 2, run)[1] for row in rows["build_full_selection"]})
    return None, suites, reasons


def selection_outcome(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    engine_error: str | None,
) -> dict[str, Any]:
    """Return the selection mode, the selected suites and the full-selection reasons of one run.

    The first failure decides: an engine failure, a missing publication, an invalid publication
    (missing required checks `rezono:proofs` / `rezono:schema`, a check that is not green, a
    check with non-zero violations, no checks, or a relation the publication did not contain),
    then the published ``build_full_selection`` reasons. Otherwise the suites of the published
    ``build_selected_job`` rows are selected. A row of another run or a malformed row is rejected.
    """
    failure, suites, reasons = resolve_selection(
        run=run, manifest=manifest, rows=rows, engine_error=engine_error
    )
    if failure is not None:
        return _full(failure)
    if reasons:
        return _full(*reasons)
    return {"mode": "selected", "suites": suites, "reasons": []}
