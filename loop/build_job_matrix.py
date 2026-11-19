"""Expand verified build selection rows to the configured CI job and shard matrix."""

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

_SHARDED = ("contracts", "python")


def _key(row: object, size: int) -> tuple[str, ...]:
    """Return the row key as strings, or raise when it does not have the expected shape."""
    key = row.get("key") if isinstance(row, Mapping) else None
    if not isinstance(key, (list, tuple)) or len(key) != size:
        raise ValueError(f"malformed selection row: {row!r}")
    if not all(isinstance(part, str) and part for part in key):
        raise ValueError(f"malformed selection row: {row!r}")
    return tuple(key)


def _suites(suites: Iterable[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    """Index the configured suites by folder and reject an unusable configuration."""
    configured: dict[str, Mapping[str, Any]] = {}
    for suite in suites:
        folder, kind = suite.get("folder"), suite.get("kind")
        if not isinstance(folder, str) or not folder or folder in configured:
            raise ValueError(f"invalid suite configuration: {suite!r}")
        if kind in _SHARDED:
            total = suite.get("total")
            if type(total) is not int or total < 1:
                raise ValueError(f"invalid shard total for suite {folder!r}")
        elif kind != "node":
            raise ValueError(f"unknown suite kind for {folder!r}: {kind!r}")
        configured[folder] = suite
    return configured


def job_matrix(
    *,
    run: str,
    selected: Sequence[Mapping[str, Any]],
    full: Sequence[Mapping[str, Any]],
    suites: Iterable[Mapping[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Return the python and node matrix items of the ci-matrix command for this run.

    ``selected`` holds verified ``build_selected_job(run, component, reason)`` rows and ``full``
    verified ``build_full_selection(run, reason)`` rows. A row of another run, a malformed row or a
    component without a configured suite is rejected. Any full-selection row selects every suite.
    """
    configured = _suites(suites)
    components: set[str] = set()
    for row in selected:
        row_run, component, _reason = _key(row, 3)
        if row_run != run:
            raise ValueError(f"selected job of another run: {row_run!r}")
        if component not in configured:
            raise ValueError(f"selected component without a configured suite: {component!r}")
        components.add(component)
    for row in full:
        row_run, _reason = _key(row, 2)
        if row_run != run:
            raise ValueError(f"full selection of another run: {row_run!r}")
    if full:
        components = set(configured)

    python: list[dict[str, Any]] = []
    node: list[dict[str, Any]] = []
    for folder in sorted(components):
        suite = configured[folder]
        kind = suite["kind"]
        if kind == "node":
            node.append({"folder": folder, "kind": kind})
            continue
        total = suite["total"]
        python.extend(
            {"folder": folder, "kind": kind, "shard": shard, "total": total,
             "label": folder if total == 1 else f"{folder} {shard + 1}/{total}"}
            for shard in range(total)
        )
    return {"python": python, "node": node}
