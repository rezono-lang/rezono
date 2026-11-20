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
