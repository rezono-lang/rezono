"""A recorded absence needs verified coverage for the same run, collector and sweep."""

import json

import pytest

from flow_drift_cases import MissingVerifiedSweepInventory, verified_sweep
from pack_records import LOOP, evaluate


RUN, SCOPE, SWEEP = "active", "inventory-reader", "morning"
TOKEN, EVENT, REASON = "widget", "item-reading", "inventory/lookup"
DRIFT = (RUN, TOKEN, TOKEN, REASON)


def receipt(run=RUN, scope=SCOPE, sweep=SWEEP, lost=0, *, start=0, stop=2):
    key = {"run": run, "collector": scope, "window": sweep}
    return {
        "flow_sweep_window": [dict(key, id="coverage", start=start, stop=stop)],
        "flow_expected_node": [dict(key, id="node-inventory", node="observer")],
        "flow_node_report": [dict(key, id="node-final", node="observer", first=start, last=stop, gaps=0, lost=lost)],
    }


def verified(run=RUN, scope=SCOPE, sweep=SWEEP, nodes=("observer",)):
    """The admitted rows of a verified receipt whose trusted inventory lists these sweep nodes."""
    return verified_sweep(nodes, (run, scope, sweep), f"receipt/{run}/{scope}/{sweep}")


def recording(coverage, **location):
    observation = {"id": EVENT, "run": RUN, "token": TOKEN, "reason": REASON,
                   "state": "absent", "event_time": 1, "value": "", **location}
    return {"loop_active_run": [{"id": RUN}], "loop_expectation": [{"id": TOKEN, "value": "present"}],
            "loop_observation": [observation], **coverage}


@pytest.mark.parametrize("coverage", [{}, receipt()], ids=["no-receipt", "unbound-receipt"])
def test_absence_report_alone_cannot_prove_drift(coverage):
    from loop.typed_recording import typed_recording
    from rezono_compiler import modules

    data = {
        "pack": {"path": LOOP.name, "sha256": modules.pack_hash(LOOP)},
        "run": RUN, "limit": 1, "ports": [], "initial": [], "sweeps": [], "records": recording(coverage),
    }
    snapshot, = typed_recording(LOOP.parent, data).snapshots()
    assert not snapshot.drift


@pytest.mark.parametrize(("coverage", "admitted", "expected"), [
    pytest.param({}, None, False, id="missing"),
    pytest.param(receipt(run="old"), verified(run="old"), False, id="other-run"),
    pytest.param(receipt(scope="other-reader"), verified(scope="other-reader"), False, id="other-scope"),
    pytest.param(receipt(sweep="evening"), verified(sweep="evening"), False, id="other-sweep"),
    pytest.param(receipt(lost=1), verified(), False, id="incomplete"),
    pytest.param(receipt(), verified(), True, id="matching"),
])
def test_absence_uses_only_matching_coverage(coverage, admitted, expected):
    from rezono_compiler import pack

    _, rows, explainer = evaluate(pack.read(LOOP), recording(coverage, scope=SCOPE, sweep=SWEEP), admitted)
    assert rows["current"] == ({(RUN, TOKEN, "absent", "", REASON)} if expected else set())
    assert rows["drift"] == ({DRIFT} if expected else set())
    if expected:
        proof = explainer.proof("drift", DRIFT, "snapshot")
        positives = {(p["row"]["relation"], tuple(json.loads(p["row"]["key"])))
                     for witness in proof["witnesses"] for p in witness["premises"] if p["polarity"] == "positive"}
        assert {
            ("loop_expectation__value", (TOKEN, "present")),
            ("loop_observation__state", (EVENT, "absent")),
            ("complete_sweep", (RUN, SCOPE, SWEEP, "coverage")),
            ("flow_sweep_window__run", ("coverage", RUN)),
        } <= positives


def test_scope_and_sweep_belong_to_one_observation():
    from rezono_compiler import pack

    data = recording(receipt(), scope=SCOPE)
    partial, = data["loop_observation"]
    data["loop_observation"].append({**partial, "id": "elsewhere", "scope": "other-reader", "sweep": SWEEP})
    _, rows, _ = evaluate(pack.read(LOOP), data, verified())
    assert not rows["current"] and not rows["drift"]


@pytest.mark.parametrize(("time", "expected"), [
    pytest.param(9, False, id="before-start"),
    pytest.param(10, True, id="at-start"),
    pytest.param(11, True, id="before-stop"),
    pytest.param(12, False, id="at-stop"),
    pytest.param(100, False, id="after-stop"),
])
def test_absence_is_only_proven_inside_the_complete_window(time, expected):
    from rezono_compiler import pack

    data = recording(receipt(start=10, stop=12), scope=SCOPE, sweep=SWEEP, event_time=time)
    _, rows, explainer = evaluate(pack.read(LOOP), data, verified())
    assert rows["current"] == ({(RUN, TOKEN, "absent", "", REASON)} if expected else set())
    assert rows["drift"] == ({DRIFT} if expected else set())
    if expected:
        proof = explainer.proof("drift", DRIFT, "snapshot")
        positives = {(p["row"]["relation"], tuple(json.loads(p["row"]["key"])))
                     for witness in proof["witnesses"] for p in witness["premises"] if p["polarity"] == "positive"}
        assert {
            ("loop_observation__event_time", (EVENT, str(time))),
            ("sweep_window", (RUN, SCOPE, SWEEP, "10", "12", "coverage")),
            ("flow_sweep_window__start", ("coverage", "10")),
            ("flow_sweep_window__stop", ("coverage", "12")),
        } <= positives


def test_incomplete_window_cannot_lend_bounds_to_the_complete_window():
    from rezono_compiler import pack

    coverage = receipt(start=10, stop=12)
    complete, = coverage["flow_sweep_window"]
    coverage["flow_sweep_window"].append({**complete, "id": "uncovered", "start": 8})
    data = recording(coverage, scope=SCOPE, sweep=SWEEP, event_time=9)
    _, rows, _ = evaluate(pack.read(LOOP), data, verified())
    assert rows["complete_sweep"] == {(RUN, SCOPE, SWEEP, "coverage")}
    assert not rows["current"] and not rows["drift"]


@pytest.mark.parametrize(("second_bounds", "time", "expected"), [
    pytest.param(None, 9, False, id="single-window-before-start"),
    pytest.param(None, 11, True, id="single-window-inside"),
    pytest.param((8, 12), 9, False, id="disagreed-start-cannot-widen"),
    pytest.param((8, 12), 11, False, id="disagreed-start-invalidates-overlap"),
    pytest.param((10, 13), 12, False, id="disagreed-stop-cannot-widen"),
    pytest.param((10, 12), 10, True, id="identical-bounds-agree"),
    pytest.param((10, 12), 12, False, id="identical-bounds-exclude-stop"),
])
def test_complete_windows_need_unambiguous_bounds(second_bounds, time, expected):
    from rezono_compiler import pack

    coverage = receipt(start=10, stop=12)
    coverage["flow_node_report"][0].update(first=8, last=13)
    if second_bounds is not None:
        start, stop = second_bounds
        original, = coverage["flow_sweep_window"]
        coverage["flow_sweep_window"].append(dict(original, id="second", start=start, stop=stop))

    data = recording(coverage, scope=SCOPE, sweep=SWEEP, event_time=time)
    _, rows, _ = evaluate(pack.read(LOOP), data, verified())

    assert rows["current"] == ({(RUN, TOKEN, "absent", "", REASON)} if expected else set())
    assert rows["drift"] == ({DRIFT} if expected else set())
    refs = {record["id"] for record in coverage["flow_sweep_window"]}
    assert rows["complete_sweep"] == (
        {(RUN, SCOPE, SWEEP, ref) for ref in refs} if second_bounds in (None, (10, 12)) else set()
    )



def test_absence_needs_verified_sweep_inventory():
    from rezono_compiler import pack

    data = recording(receipt(), scope=SCOPE, sweep=SWEEP)
    cases = {
        "matching": (verified(), True),
        "no-receipt": (None, False),
        "receipt-for-other-run": (verified(run="old"), False),
        "receipt-for-other-scope": (verified(scope="other-reader"), False),
        "receipt-for-other-sweep": (verified(sweep="evening"), False),
        "unreported-member": (verified(nodes=("observer", "second")), False),
    }
    for name, (admitted, expected) in cases.items():
        _, rows, _ = evaluate(pack.read(LOOP), data, admitted)
        sweeps = {(RUN, SCOPE, SWEEP, "coverage")} if expected else set()
        if rows["complete_sweep"] != sweeps or rows["drift"] != ({DRIFT} if expected else set()):
            raise MissingVerifiedSweepInventory(
                f"{name}: complete_sweep {rows['complete_sweep']}, drift {rows['drift']}")
