"""Counterexample tests for std-loop ready scoping, quiet-round deadlines, and sentinel-free delivery status."""

from pack_records import LOOP, evaluate


def _round_records(active_runs, receipts, steps):
    return {
        "loop_active_run": [{"id": run} for run in active_runs],
        "loop_sweep_receipt": [
            {"id": cut, "run": run, "event_time": time}
            for cut, run, time in receipts
        ],
        "loop_step": [{"id": step} for step in steps],
    }


def test_ready_blocks_same_label_conflicting_rounds_without_leaking_across_runs():
    from rezono_compiler import pack

    model = pack.read(LOOP)
    data = _round_records(
        active_runs=("run-1", "run-2"),
        receipts=(("cut-1", "run-1", 10), ("cut-2", "run-2", 10)),
        steps=("step-a", "step-b", "step-c"),
    )

    # Two distinct verified rounds for the same (run, cut) sharing the same batch label must leave
    # run-1 undecided without blocking run-2, which unambiguously uses that same batch label.
    same_label = {
        "verified_round": [
            ("round-1a", "run-1", "cut-1", "shared-batch"),
            ("round-1b", "run-1", "cut-1", "shared-batch"),
            ("round-2a", "run-2", "cut-2", "shared-batch"),
        ],
        "verified_round_member": [
            ("round-1a", "step-a"),
            ("round-1b", "step-b"),
            ("round-2a", "step-c"),
        ],
    }
    _, rows, _ = evaluate(model, data, verified=same_label)
    ready_pairs = {(run, step) for run, step, _ in rows["ready"]}
    assert {step for run, step in ready_pairs if run == "run-1"} == set(), (
        f"Conflicting same-label rounds made run-1 steps ready: {rows['ready']}"
    )
    assert {step for run, step in ready_pairs if run == "run-2"} == {"step-c"}, (
        f"Conflict in run-1 leaked to run-2: {rows['ready']}"
    )
    assert ("run-1", "cut-1") in rows["ready_round_ambiguous"]
    assert ("run-2", "cut-2") not in rows["ready_round_ambiguous"]
    assert ("run-1", "cut-1") in rows["loop_batch_undecided"]
    assert ("run-2", "cut-2") not in rows["loop_batch_undecided"]

    # Two conflicting rounds with different batch labels in run-1 must not block run-2 when run-2
    # unambiguously selects one of those batch labels.
    diff_labels = {
        "verified_round": [
            ("round-1a", "run-1", "cut-1", "batch-x"),
            ("round-1b", "run-1", "cut-1", "batch-y"),
            ("round-2a", "run-2", "cut-2", "batch-x"),
        ],
        "verified_round_member": [
            ("round-1a", "step-a"),
            ("round-1b", "step-b"),
            ("round-2a", "step-c"),
        ],
    }
    _, rows, _ = evaluate(model, data, verified=diff_labels)
    ready_pairs = {(run, step) for run, step, _ in rows["ready"]}
    assert {step for run, step in ready_pairs if run == "run-1"} == set()
    assert {step for run, step in ready_pairs if run == "run-2"} == {"step-c"}
    assert rows["loop_selected_batch"] == {("batch-x",)}


def _deadline_scenario(observations):
    return {
        "loop_active_run": [{"id": "current"}],
        "loop_step": [{"id": "publish"}],
        "loop_completion": [
            {"id": "completion", "run": "current", "step": "publish", "token": "released", "reason": "completion"},
        ],
        "loop_expectation": [
            {"id": "started", "value": "yes"},
            {"id": "released", "value": "yes"},
        ],
        "loop_observation": [
            {"id": "start", "run": "current", "token": "started", "event_time": 10,
             "state": "known", "value": "yes", "reason": "start"},
            *observations,
        ],
        "loop_deadline": [
            {"id": "deadline", "run": "current", "step": "publish", "start": "start", "budget": 5},
        ],
        "loop_sweep": [
            {"id": "after-boundary", "run": "current", "event_time": 20, "complete": True},
        ],
    }


def _obs(key, time, value="yes", state="known"):
    return {
        "id": key, "run": "current", "token": "released", "event_time": time,
        "state": state, "value": value, "reason": key,
    }


def test_quiet_round_done_in_time_refuses_pre_start_conflicting_and_regressed_observations():
    from rezono_compiler import pack

    model = pack.read(LOOP)

    bad_histories = {
        "pre_start_only": [_obs("stale", 5, "yes")],
        "pre_start_then_late": [_obs("stale", 5, "yes"), _obs("late", 16, "yes")],
        "conflicting_value_then_late": [
            _obs("good-12", 12, "yes"),
            _obs("bad-12", 12, "no"),
            _obs("late-16", 16, "yes"),
        ],
        "conflicting_unknown_then_late": [
            _obs("good-12", 12, "yes"),
            _obs("unk-12", 12, "", state="unknown"),
            _obs("late-16", 16, "yes"),
        ],
        "regressed_value_then_late": [
            _obs("good-12", 12, "yes"),
            _obs("regressed-14", 14, "no"),
            _obs("late-16", 16, "yes"),
        ],
        "regressed_unknown_then_late": [
            _obs("good-12", 12, "yes"),
            _obs("regressed-14", 14, "", state="unknown"),
            _obs("late-16", 16, "yes"),
        ],
        "regressed_after_boundary_then_late": [
            _obs("good-12", 12, "yes"),
            _obs("regressed-16", 16, "no"),
            _obs("late-18", 18, "yes"),
        ],
    }
    for name, history in bad_histories.items():
        _, rows, _ = evaluate(model, _deadline_scenario(history))
        assert ("current", "publish", "deadline") not in rows["done_in_time"], (
            f"{name} wrongly satisfied done_in_time: {rows['done_in_time']}"
        )
        assert any(row[:3] == ("current", "publish", "after-boundary") for row in rows["deadline_expired"]), (
            f"{name} did not expire deadline: {rows['deadline_expired']}"
        )
        assert rows["round_outcome"] == {("current", "failure")}, f"{name} outcome: {rows['round_outcome']}"

    # Positive control: earlier non-matching value followed by clean in-window completion and
    # harmless post-boundary re-observation satisfies done_in_time.
    good_history = [
        _obs("not-yet-11", 11, "no"),
        _obs("done-13", 13, "yes"),
        _obs("reconfirmed-16", 16, "yes"),
    ]
    _, rows, _ = evaluate(model, _deadline_scenario(good_history))
    assert ("current", "publish", "deadline") in rows["done_in_time"]
    assert rows["deadline_expired"] == set()
    assert rows["round_outcome"] == {("current", "success")}


def test_delivery_status_uses_optional_time_and_explicit_unknown_state():
    from rezono_compiler import pack

    from loop.status_projection import project_status

    model = pack.read(LOOP)
    step = {"tenant": "elm", "delivery": "elm-1", "step": "database", "run": "r1"}
    scope_key = ("elm", "elm-1", "database", "r1")

    # Direct pack evaluation with an undated observation (both at and event_time omitted).
    undated = {**step, "id": "ev-1", "relation": "done", "reason": "https://example.org/done"}
    _, rows, _ = evaluate(model, {"loop_status_observation": [undated]})
    assert rows["status_latest"] == set(), f"Undated observation invented a latest instant: {rows['status_latest']}"
    assert rows["status_reading"] == set(), f"Undated observation entered dated readings: {rows['status_reading']}"
    assert (*scope_key, "ev-1", "success", "https://example.org/done") in rows["status_reading_time_unknown"]
    assert rows["status_time_state"] == {(*scope_key, "unknown")}
    assert rows["current_delivery_status"] == {(*scope_key, "success", "https://example.org/done")}

    # Status projection omits sentinel values and reports explicit unknown time state.
    projection = project_status(step, [{**step, "relation": "done", "reason": "https://example.org/done"}])
    assert projection.state == "success"
    assert projection.latest_at is None
    assert projection.time_state == "unknown"
    assert all("at" not in obs and "event_time" not in obs for obs in projection.observations)

    # Dated observation reports explicit known time state and its timestamp.
    dated = {**step, "relation": "done", "reason": "https://example.org/done", "at": "2026-01-01T00:00:00Z"}
    dated_projection = project_status(step, [dated])
    assert dated_projection.state == "success"
    assert dated_projection.latest_at == "2026-01-01T00:00:00Z"
    assert dated_projection.time_state == "known"
    assert all("at" in obs and "event_time" in obs and obs["event_time"] >= 0 for obs in dated_projection.observations)

    # Mixing a dated observation with an undated disagreeing observation stays pending with unknown time state.
    mixed_stuck = {**step, "id": "ev-2", "relation": "stuck", "reason": "https://example.org/stuck"}
    mixed_done = {**step, "id": "ev-3", "relation": "done", "reason": "https://example.org/done",
                  "at": "2026-01-01T00:00:00Z", "event_time": 0}
    _, rows, _ = evaluate(model, {"loop_status_observation": [mixed_stuck, mixed_done]})
    assert rows["status_time_state"] == {(*scope_key, "unknown")}
    assert rows["status_conflict"] == {scope_key}
    assert rows["current_delivery_status"] == {
        (*scope_key, "pending", "https://example.org/done"),
        (*scope_key, "pending", "https://example.org/stuck"),
    }
