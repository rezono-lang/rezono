import pytest

from case_support import ROOT, engine


def test_renaming_roles_and_zones_preserves_findings():
    from rezono_compiler import scenarios
    from rules_support import State, states

    model, program, _ = states(ROOT)
    baseline = engine()[1]
    names = {v: "renamed-" + v for v in ("external", "entry", "recovery", "build", "tenant")}
    label, rows = next(iter(scenarios.states(model, ROOT)))
    def rename(row):
        return tuple(names.get(cell, cell) for cell in row)
    changed = State(model, program, label, {t: [rename(row) for row in values] for t, values in rows.items()})
    for name in ("outside_reaches_inside", "recovery_reached", "recovery_reaches_out", "verified",
                 "unverified_supply", "build_reaches_tenant"):
        assert changed.derived[name] == {rename(row) for row in baseline.derived[name]}, name
