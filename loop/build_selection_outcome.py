"""Turn a build publication, or its absence, into a suite selection or full checks with the reason."""

from collections.abc import Mapping, Sequence
from typing import Any

_RELATIONS = {"build_selected_job": 3, "build_full_selection": 2}


def _full(*reasons: str) -> dict[str, Any]:
    return {"mode": "full", "suites": [], "reasons": list(reasons)}


def _green(manifest: Mapping[str, Any]) -> bool:
    """Return whether the publication manifest carries at least one check and every check is green."""
    checks = manifest.get("checks")
    if not isinstance(checks, Sequence) or isinstance(checks, (str, bytes)) or not checks:
        return False
    return all(isinstance(check, Mapping) and check.get("status") == "green" for check in checks)


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


def selection_outcome(
    *,
    run: str,
    manifest: Mapping[str, Any] | None,
    rows: Mapping[str, Sequence[Mapping[str, Any]]] | None,
    engine_error: str | None,
) -> dict[str, Any]:
    """Return the selection mode, the selected suites and the full-selection reasons of one run.

    The first failure decides: an engine failure, a missing publication, an invalid publication
    (a check that is not green, no checks, or a relation the publication did not contain), then the
    published ``build_full_selection`` reasons. Otherwise the suites of the published
    ``build_selected_job`` rows are selected. A row of another run or a malformed row is rejected.
    """
    if engine_error:
        return _full("engine-failure")
    if manifest is None or rows is None:
        return _full("missing-publication")
    if not isinstance(manifest, Mapping) or not _green(manifest):
        return _full("invalid-publication")
    if not isinstance(rows, Mapping) or any(
        not isinstance(rows.get(name), Sequence) or isinstance(rows.get(name), (str, bytes)) for name in _RELATIONS
    ):
        return _full("invalid-publication")
    suites = {_key(row, 3, run)[1] for row in rows["build_selected_job"]}
    reasons = {_key(row, 2, run)[1] for row in rows["build_full_selection"]}
    if reasons:
        return _full(*sorted(reasons))
    return {"mode": "selected", "suites": sorted(suites), "reasons": []}
