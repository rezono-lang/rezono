"""Releases are ordered by the date their maker published, not by a number written beside them
(decisions/platform-facts-not-conclusions.md, section 4).

The expected rows are the independent reference rows of oracle-rows.json, which the oracle computes from the day
numbers until a planner retires them; Keycloak 26.0.0's date is the publisher's, as acceptance/product-evidence.json
records it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

PLATFORM = Path(__file__).resolve().parent


def _rows():
    from rezono_compiler import scenarios
    from rules_support import states

    model, prog, _ = states(PLATFORM)
    label, raw = next(iter(scenarios.states(model, PLATFORM)))
    return model, prog, label, {table: list(values) for table, values in raw.items()}


def _derive(model, prog, label, rows):
    from rules_support import State

    return State(model, prog, label, rows).derived


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M3: decisions/platform-facts-not-conclusions.md, section 4. Derive released_on(r, d) from the "
    "ProductReleaseSource whose product and version are the release's, with published as a date slot; order stable "
    "releases by it in native date order (no newest_day, no @days), and give a product with an undated stable "
    "release no newest one (release_undated). Keep released_on_day for now: no rule reads it, and a planner retires "
    "it. Waits for compiler/tests/test_std_decision_dates.py--test_std_decision_rules_read_dates and the planner's "
    "sources step of section 4."))
def test_runs_orders_releases_by_their_sourced_date():
    reference = json.loads((PLATFORM / "oracle-rows.json").read_text(encoding="utf-8"))
    keycloak = json.loads((PLATFORM / "acceptance/product-evidence.json").read_text(encoding="utf-8"))["keycloak"]
    model, prog, label, rows = _rows()
    assert "release__released_on_day" not in prog.base_used(), "a rule still orders releases by released_on_day"
    derived = _derive(model, prog, label, rows)
    released = dict(derived.get("released_on", ()))
    assert released.get("keycloak-26") == keycloak["published"], released
    stable = {release for release, value in rows["release__stable"] if value == "yes"}
    assert stable <= set(released), f"stable releases without a dated statement: {sorted(stable - set(released))}"
    assert derived["runs"] == {tuple(map(str, row)) for row in reference["runs"]}
    assert derived["behind_newest"] == {tuple(map(str, row)) for row in reference["behind_newest"]}

    # The day numbers decide nothing, while they are still written.
    if "release__released_on_day" in rows:
        changed = dict(rows, release__released_on_day=[(r, -day) for r, day in rows["release__released_on_day"]])
        assert _derive(model, prog, label, changed)["runs"] == derived["runs"], "runs still reads released_on_day"

    # The dates decide: with the two Keycloak dates exchanged, keycloak-25 is the newest stable release.
    version = dict(rows["release__version"])
    product = dict(rows["product_release_source__product"])
    stated = dict(rows["product_release_source__version"])

    def statement(release):
        found = [s for s, of in product.items() if of == "keycloak" and stated.get(s) == version.get(release)]
        assert len(found) == 1, (release, found)
        return found[0]

    older, newer = statement("keycloak-25"), statement("keycloak-26")
    dates = dict(rows["product_release_source__published"])
    swapped = {older: dates[newer], newer: dates[older]}
    changed = dict(rows, product_release_source__published=[
        (s, swapped.get(s, day)) for s, day in rows["product_release_source__published"]])
    runs = _derive(model, prog, label, changed)["runs"]
    assert ("idp", "keycloak-25") in runs and ("idp", "keycloak-26") not in runs
