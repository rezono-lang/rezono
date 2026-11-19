"""Successor support is checked on the first unsupported day, including both endpoints."""
import pytest

from case_support import ROOT, verified
from rezono_compiler import calc, facts, pack, rules
from rules_support import State


class MissingPlatformRule(Exception):
    pass


def evaluate(model, program, records):
    calculation = calc.build(model, model.calc) if program.calc_inputs() else None
    return State(model, program, "platform-case", facts.rows_of(model, records), calculation)

from datetime import date, timedelta


def expected(first_unsupported, window):
    if window is None:
        return "missing_successor"
    start, end = window
    return "covered" if start <= first_unsupported < end else "support_gap"


def test_half_open_handoff_dates():
    assert [expected(20, w) for w in [(20, 30), (21, 30), (10, 20), None]] == [
        "covered", "support_gap", "support_gap", "missing_successor"]


def decision(key):
    return {"id": key, "title": key, "decider": ["panel"], "state": "in_force",
            "valid_from": "2026-03-01", "valid_from_day": 20260301}


def test_successor_on_the_first_day_without_support():
    model = pack.read(ROOT)
    program = rules.load(model.rules)
    result, impact = "successor_finding", "successor_impact"
    if not {result, impact} <= set(program.derived()):
        raise MissingPlatformRule("successor_finding and successor_impact")
    assert program.reaches("in_force_on", result) and program.reaches("holds_at", result)
    for late_start in (21, 20):
        windows = {"willow": (20, 34), "cinder": (late_start, 33), "frost": (9, 20), "quill": None}
        periods, stances, successors, uses, needs, decisions = [], [], [], [], [], []
        for p, window in windows.items():
            decisions.append(decision(f"phase-{p}"))
            stances.append({"id": f"phase-{p}", "decision": f"phase-{p}", "product": p,
                            "stance": "phase_out", "period": f"old-{p}"})
            periods.append({"id": f"old-{p}", "on_axis": "days", "start": 7, "end": 20})
            if window:
                decisions.append(decision(f"next-{p}"))
                successors.append({"id": f"next-{p}", "decision": f"next-{p}", "old": p,
                                   "new": f"{p}-next", "period": f"new-{p}"})
                periods.append({"id": f"new-{p}", "on_axis": "days", "start": window[0], "end": window[1]})
            uses.append({"id": f"use-{p}", "service": f"{p}-api", "product": p})
            needs.extend([{"id": f"edge-{p}", "consumer": f"{p}-client", "provider": f"{p}-api", "mode": "run"},
                          {"id": f"path-{p}", "consumer": f"{p}-sink", "provider": f"{p}-client", "mode": "run"}])
        day = date(2026, 3, 1) + timedelta(days=19)
        records = {"decision": decisions, "reference_date": [{"id": "handoff", "title": day.isoformat(),
                   "day": int(day.strftime("%Y%m%d"))}], "axis": [{"id": "days"}],
                   "reference_point": [{"id": "handoff", "on_axis": "days", "position": 20, "horizon": 0}],
                   "platform_support_period": periods, "product_stance": stances, "product_successor": successors,
                   "service_product_use": uses, "service_need": needs}
        state = evaluate(model, program, records)
        wanted = {(p, expected(20, window)) for p, window in windows.items() if expected(20, window) != "covered"}
        assert state.derived[result] == wanted
        assert state.derived[impact] == {(p, f"{p}-{suffix}") for p, reason in wanted for suffix in ("api","client","sink")}
        for p, reason in wanted:
            leaves = verified(result, (p, reason), state=(model, state))
            assert ("interval__end", (f"old-{p}", "20")) in leaves
            assert ("product_stance__decision", (f"phase-{p}", f"phase-{p}")) in leaves
            if windows[p]:
                slot = "start" if windows[p][0] > 20 else "end"
                assert (f"interval__{slot}", (f"new-{p}", str(windows[p][slot == "end"]))) in leaves
            downstream = verified(impact, (p, f"{p}-sink"), state=(model, state))
            assert {("service_product_use__product", (f"use-{p}", p)),
                    ("service_need__provider", (f"edge-{p}", f"{p}-api")),
                    ("service_need__provider", (f"path-{p}", f"{p}-client"))} <= downstream


class SuccessorImpactStopsEarly(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=SuccessorImpactStopsEarly, reason=(
    "M2: decisions/platform-successor-window.md: Derive successor_impact in examples/platform/rules/product_succession.dl "
    "through a recursive closure over running service_need rows, the same relation as unavailable_service in "
    "examples/platform/rules/outage.dl, so every running consumer at any number of steps is affected and a change-only "
    "need is not."))
def test_successor_impact_follows_every_running_step():
    model = pack.read(ROOT)
    program = rules.load(model.rules)
    chain = ["quill-api", "quill-client", "quill-sink", "quill-far", "quill-farther"]
    needs = [{"id": f"run-{consumer}", "consumer": consumer, "provider": provider, "mode": "run"}
             for provider, consumer in zip(chain, chain[1:])]
    needs.append({"id": "change-quill-admin", "consumer": "quill-admin", "provider": "quill-sink", "mode": "change"})
    needs.append({"id": "run-quill-audit", "consumer": "quill-audit", "provider": "quill-admin", "mode": "run"})
    day = date(2026, 3, 1) + timedelta(days=19)
    records = {"decision": [decision("phase-quill")],
               "reference_date": [{"id": "handoff", "title": day.isoformat(), "day": int(day.strftime("%Y%m%d"))}],
               "axis": [{"id": "days"}],
               "reference_point": [{"id": "handoff", "on_axis": "days", "position": 20, "horizon": 0}],
               "platform_support_period": [{"id": "old-quill", "on_axis": "days", "start": 7, "end": 20}],
               "product_stance": [{"id": "phase-quill", "decision": "phase-quill", "product": "quill",
                                   "stance": "phase_out", "period": "old-quill"}],
               "product_successor": [],
               "service_product_use": [{"id": "use-quill", "service": "quill-api", "product": "quill"}],
               "service_need": needs}
    state = evaluate(model, program, records)
    assert state.derived["successor_finding"] == {("quill", "missing_successor")}
    impact = state.derived["successor_impact"]
    assert {("quill", service) for service in chain[:3]} <= impact
    missing = {("quill", service) for service in chain} - impact
    if missing:
        raise SuccessorImpactStopsEarly(f"running consumers without impact: {sorted(missing)}")
    assert impact == {("quill", service) for service in chain}
    downstream = verified("successor_impact", ("quill", "quill-farther"), state=(model, state))
    assert {("service_product_use__product", ("use-quill", "quill"))} | {
        ("service_need__provider", (f"run-{consumer}", provider)) for provider, consumer in zip(chain, chain[1:])
    } <= downstream
