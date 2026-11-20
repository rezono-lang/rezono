"""The support window reads the release a service runs, not a second record of it
(decisions/platform-facts-not-conclusions.md, section 6).

The windows and the expected rows are those of acceptance/test_support_window.py, from the maker's pinned support
statement recorded in acceptance/product-evidence.json; the running version 1.32.13 is the one
facts/support_window.yaml records at b77fd2a.
"""

from __future__ import annotations

from datetime import date
import json
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parent
EPOCH = date(1970, 1, 1)
WINDOWS = (("2026-02-01", 26), ("2026-02-01", 27), ("2026-02-28", 0), ("2026-03-01", 30))
RUNNING = "1.32.13"


def _rows():
    from rezono_compiler import scenarios
    from rules_support import states

    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    return model, prog, label, {table: list(values) for table, values in raw.items()}


def _derive(model, prog, label, rows):
    from rules_support import State

    return State(model, prog, label, rows).derived


def _query(day: str, horizon: int) -> dict:
    as_of = date.fromisoformat(day)
    return {"support_query": [("query",)], "support_query__as_of_day": [("query", (as_of - EPOCH).days)],
            "support_query__horizon_days": [("query", horizon)]}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M2: decisions/platform-facts-not-conclusions.md, section 6. support_window_result reads runs(s, r) and the "
    "release's version, series and product instead of supported_service_release. Keep the retired fact file: a "
    "planner removes it. Waits for the planner's sources steps of sections 4 and 6 (the release "
    "kube-control-1.32.13 pinned for cp, and kube-control as the one product id of the support register)."))
def test_support_window_reads_the_release_the_service_runs():
    source = json.loads((PLATFORM / "acceptance/product-evidence.json").read_text(encoding="utf-8"))["kubernetes"]
    end = date.fromisoformat(source["end"])
    model, prog, label, rows = _rows()
    running = {release for service, release in _derive(model, prog, label, rows)["runs"] if service == "cp"}
    assert len(running) == 1, f"cp runs {sorted(running)}"
    release, = running
    assert dict(rows["release__version"]).get(release) == RUNNING

    def window(changed, day, horizon):
        return _derive(model, prog, label, changed | _query(day, horizon))["support_window_result"]

    def expected(version):
        return {("query", "cp", version, source["end"], source["url"], source["sha256"])}

    for day, horizon in WINDOWS:
        inside = 0 <= (end - date.fromisoformat(day)).days <= horizon
        assert window(rows, day, horizon) == (expected(RUNNING) if inside else set()), (day, horizon)

    # The release cp runs gives the version.
    patched = dict(rows, release__version=[
        (r, "1.32.12" if r == release else version) for r, version in rows["release__version"]])
    assert window(patched, "2026-02-01", 27) == expected("1.32.12")

    # The retired record decides nothing, while it is still written.
    if "supported_service_release__version" in rows:
        stale = dict(rows, supported_service_release__version=[
            (r, "0.0.0") for r, _ in rows["supported_service_release__version"]])
        assert window(stale, "2026-02-01", 27) == expected(RUNNING)
