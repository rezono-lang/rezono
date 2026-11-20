"""Waiting time and completion time of a delivery step are std-loop rows: decisions/code-does-not-decide.md.

The expectation is the behaviour of loop/status_times.py and decisions/delivery-commit-status.md: waiting time
is the elapsed event time since the step entered waiting, up to its completion or else the latest sweep of the
same run, and a completion time is published only from a completion observation of that run.
"""
import pytest

from pack_records import LOOP, evaluate

SCOPE = {"tenant": "elm", "delivery": "elm-1", "step": "database", "run": "r"}
RELATIONS = ("delivery_waiting_time", "delivery_completed_at")


def reading(key, relation, seconds, **overrides):
    return {"id": key, **SCOPE, "relation": relation, "reason": key,
            "at": f"2030-01-01T10:{seconds // 60:02}:00Z", "event_time": seconds, **overrides}


def sweep(key, seconds, run="r"):
    return {"id": key, "run": run, "event_time": seconds, "complete": True}


def times(readings, sweeps):
    from rezono_compiler import pack, rules

    model = pack.read(LOOP)
    missing = set(RELATIONS) - set(rules.load(model.rules).derived())
    assert not missing, f"std-loop does not derive {sorted(missing)}"
    data = {"loop_active_run": [{"id": "r"}], "loop_status_observation": readings, "loop_sweep": sweeps}
    _, rows, _ = evaluate(model, data)
    key = tuple(SCOPE[column] for column in ("tenant", "delivery", "step", "run"))
    waited = {int(row[-1]) for row in rows["delivery_waiting_time"] if row[:4] == key}
    completed = {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key}
    return waited, completed


def test_delivery_times_are_rows_of_the_loop_pack():
    waiting = reading("waiting", "waiting", 240)
    watermark = sweep("watermark", 420)
    foreign = sweep("foreign", 900, run="prior")
    assert times([waiting, reading("old-done", "done", 360, run="old")], [watermark, foreign]) == ({180}, set())
    done = reading("done", "done", 540)
    assert times([done, waiting], [watermark]) == ({300}, {done["at"]})
    assert times([], []) == (set(), set())
    assert times([done], [watermark]) == (set(), {done["at"]})


def _undated_reading(key, relation, **overrides):
    return {"id": key, **SCOPE, "relation": relation, "reason": key, **overrides}


def _evaluate_delivery_rows(readings, sweeps):
    from rezono_compiler import pack

    model = pack.read(LOOP)
    data = {"loop_active_run": [{"id": "r"}], "loop_status_observation": readings, "loop_sweep": sweeps}
    _, rows, _ = evaluate(model, data)
    key = tuple(SCOPE[column] for column in ("tenant", "delivery", "step", "run"))
    return key, rows


def test_undated_done_blocks_sweep_fallback_and_completion_time():
    waiting = reading("waiting", "waiting", 240)
    watermark = sweep("watermark", 420)
    later_done = reading("done-dated", "done", 540)

    # Dated waiting + undated done + sweep: time state is unknown, no completion time, no fallback to latest_sweep.
    for variant_name, undated_done in (
        ("omitted_fields", _undated_reading("done-undated", "done")),
        ("empty_at", _undated_reading("done-empty-at", "done", at="", event_time=300)),
        ("missing_event_time", _undated_reading("done-no-tick", "done", at="2030-01-01T10:05:00Z")),
    ):
        key, rows = _evaluate_delivery_rows([waiting, undated_done], [watermark])
        assert {row[-1] for row in rows["status_time_state"] if row[:4] == key} == {"unknown"}, variant_name
        assert key in rows["delivery_done_undated"], variant_name
        assert {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key} == set(), variant_name
        assert {row[-1] for row in rows["delivery_waiting_end"] if row[:4] == key} == set(), variant_name
        assert {row[-1] for row in rows["delivery_waiting_time"] if row[:4] == key} == set(), variant_name

    # Dated waiting + undated done + later dated done: undated done blocks completion time and waiting duration.
    key, rows = _evaluate_delivery_rows(
        [waiting, _undated_reading("done-undated", "done"), later_done],
        [watermark],
    )
    assert {row[-1] for row in rows["status_time_state"] if row[:4] == key} == {"unknown"}
    assert key in rows["delivery_done_undated"]
    assert {row[-1] for row in rows["delivery_done_earliest"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_waiting_end"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_waiting_time"] if row[:4] == key} == set()

    # An undated done from another run does not block waiting time in the current run.
    key, rows = _evaluate_delivery_rows(
        [waiting, _undated_reading("old-done-undated", "done", run="old")],
        [watermark],
    )
    assert key not in rows["delivery_done_undated"]
    assert {int(row[-1]) for row in rows["delivery_waiting_time"] if row[:4] == key} == {180}
    assert {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key} == set()


def test_undated_waiting_blocks_waiting_start_and_waiting_time():
    waiting_dated = reading("waiting-dated", "waiting", 240)
    waiting_undated = _undated_reading("waiting-undated", "waiting")
    done_dated = reading("done-dated", "done", 540)
    watermark = sweep("watermark", 420)

    # Undated waiting + dated waiting + dated done: waiting start/time are unknown, completion time stays known.
    key, rows = _evaluate_delivery_rows([waiting_undated, waiting_dated, done_dated], [watermark])
    assert {row[-1] for row in rows["status_time_state"] if row[:4] == key} == {"unknown"}
    assert key in rows["delivery_waiting_undated"]
    assert {row[-1] for row in rows["delivery_waiting_start"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_waiting_time"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key} == {done_dated["at"]}

    # Undated waiting + dated waiting + sweep (no done): waiting start/time are also unknown.
    key, rows = _evaluate_delivery_rows([waiting_undated, waiting_dated], [watermark])
    assert {row[-1] for row in rows["status_time_state"] if row[:4] == key} == {"unknown"}
    assert key in rows["delivery_waiting_undated"]
    assert {row[-1] for row in rows["delivery_waiting_start"] if row[:4] == key} == set()
    assert {row[-1] for row in rows["delivery_waiting_time"] if row[:4] == key} == set()

    # An undated waiting from another run does not block waiting time in the current run.
    key, rows = _evaluate_delivery_rows(
        [_undated_reading("old-waiting-undated", "waiting", run="old"), waiting_dated, done_dated],
        [watermark],
    )
    assert key not in rows["delivery_waiting_undated"]
    assert {int(row[-1]) for row in rows["delivery_waiting_start"] if row[:4] == key} == {240}
    assert {int(row[-1]) for row in rows["delivery_waiting_time"] if row[:4] == key} == {300}
    assert {row[-1] for row in rows["delivery_completed_at"] if row[:4] == key} == {done_dated["at"]}
