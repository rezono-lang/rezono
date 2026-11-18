"""A recorded absence needs independent coverage for the same run, collector and sweep."""

import json

import pytest

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


@pytest.mark.parametrize(("coverage", "expected"), [
    pytest.param({}, False, id="missing"),
    pytest.param(receipt(run="old"), False, id="other-run"),
    pytest.param(receipt(scope="other-reader"), False, id="other-scope"),
    pytest.param(receipt(sweep="evening"), False, id="other-sweep"),
    pytest.param(receipt(lost=1), False, id="incomplete"),
    pytest.param(receipt(), True, id="matching"),
])
def test_absence_uses_only_matching_coverage(coverage, expected):
    from rezono_compiler import pack

    _, rows, explainer = evaluate(pack.read(LOOP), recording(coverage, scope=SCOPE, sweep=SWEEP))
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
    _, rows, _ = evaluate(pack.read(LOOP), data)
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
    _, rows, explainer = evaluate(pack.read(LOOP), data)
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
    _, rows, _ = evaluate(pack.read(LOOP), data)
    assert rows["complete_sweep"] == {(RUN, SCOPE, SWEEP, "coverage")}
    assert not rows["current"] and not rows["drift"]
