"""Close a protected build observation over its exact selection inventory."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from rezono_compiler import facts

if TYPE_CHECKING:
    from rezono_compiler.pack import Pack

RUN_FIELDS = ("event", "base_sha", "head_sha", "engine_sha", "observed_at", "receipt")


def seal_selection_inventory(model: "Pack", records: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Seal the observer's complete projection before passing it to publication."""
    if "build_selection_cut" in records or "period_close" in records:
        raise ValueError("the selection inventory already has a receipt")
    run, = records["build_run"]
    run_id, receipt = run["id"], run["receipt"]
    observed_on = (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=run["observed_at"])).date().isoformat()
    scoped = {
        **records,
        "build_selection_cut": [{"id": run_id, "run": run_id, "observed_on": observed_on,
                                 **{field: run[field] for field in RUN_FIELDS}}],
        **{kind: [{**row, "run": run_id} for row in records.get(kind, [])]
           for kind in ("build_manifest", "build_dependency")},
    }
    [(cut, digest)] = facts.rows_of(model, scoped)["build_selection_cut__row_sha256"]
    if cut != run_id:
        raise ValueError("selection inventory does not belong to the observed run")
    return {
        **scoped,
        "period_close": [{"id": receipt, "closed_until": observed_on,
                          "covers": [{"element": cut, "sha256": digest}]}],
    }


def verify_selection_inventory(trusted: dict[str, list[dict]], keys: Callable[[str], set[tuple[str, ...]]]) -> None:
    """Check the published, checker-verified seal against the protected observer's copy."""
    [run] = trusted["build_run"]
    [close] = trusted["period_close"]
    [cover] = close["covers"]
    cut, digest, receipt = cover["element"], cover["sha256"], close["id"]
    covers = keys("period_close__covers")
    if len(covers) != 1:
        raise ValueError("publication does not match the protected selection inventory")
    [(_, cover_id)] = covers
    expected = {
        "build_run": {(cut,)},
        **{f"build_run__{field}": {(cut, str(run[field]))} for field in RUN_FIELDS},
        "loop_sweep_receipt": {(receipt,)},
        "loop_sweep_receipt__run": {(receipt, cut)},
        "loop_sweep_receipt__event_time": {(receipt, str(run["observed_at"]))},
        "period_close": {(receipt,)},
        "period_close__covers": {(receipt, cover_id)},
        "period_close__closed_until": {(receipt, close["closed_until"])},
        "build_selection_cover__element": {(cover_id, cut)},
        "build_selection_cover__sha256": {(cover_id, digest)},
        "build_selection_cut": {(cut,)},
        "build_selection_cut__run": {(cut, cut)},
        "build_selection_cut__receipt": {(cut, receipt)},
        "build_selection_cut__row_sha256": {(cut, digest)},
    }
    suites = trusted.get("build_component", [])
    expected["build_component"] = {(suite["id"],) for suite in suites}
    for field in ("run", "folder", "kind"):
        expected[f"build_component__{field}"] = {(suite["id"], suite[field]) for suite in suites}
    if any(keys(relation) != rows for relation, rows in expected.items()):
        raise ValueError("publication does not match the protected selection inventory")
