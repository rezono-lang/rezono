"""Report elapsed waiting and completion only from current step evidence, and compare the
independent test oracle (`loop/tests/status_times.py`) directly against the compiled
`packs/std-loop` rules `delivery_waiting_time` and `delivery_completed_at`."""

from pack_records import LOOP, evaluate
from status_times import times


def test_status_times():
    from rezono_compiler import pack

    scope = {"run": "r", "tenant": "elm", "delivery": "elm-1", "step": "database"}
    key = (scope["tenant"], scope["delivery"], scope["step"], scope["run"])

    def event(state, minute, **overrides):
        return {**scope, "state": state, "at": f"2030-01-01T10:{minute:02}:00Z", **overrides}

    wait = event("waiting", 4)
    watermark = event("sweep", 7)
    done = event("done", 9)
    assert times(scope, [watermark, wait, event("done", 6, run="old")]) == (180, None)
    assert times(scope, [done, wait, watermark]) == (300, done["at"])
    assert times(scope, []) == (None, None)

    # Compare the independent `status_times.times` oracle directly against compiled `std-loop`
    # `delivery_waiting_time` and `delivery_completed_at` rules across representative cases.
    model = pack.read(LOOP)

    def make_event(event_id, state, minute, **overrides):
        return event_id, minute * 60, event(state, minute, **overrides)

    cases = (
        (
            "waiting-to-sweep-ignores-foreign-run",
            [
                make_event("w1", "waiting", 4),
                make_event("s1", "sweep", 7),
                make_event("d-old", "done", 6, run="old"),
                make_event("s-old", "sweep", 15, run="prior"),
            ],
        ),
        (
            "waiting-to-done-over-sweep",
            [
                make_event("d1", "done", 9),
                make_event("w1", "waiting", 4),
                make_event("s1", "sweep", 7),
            ],
        ),
        (
            "latest-waiting-before-earliest-done",
            [
                make_event("w1", "waiting", 2),
                make_event("w2", "waiting", 5),
                make_event("w-after", "waiting", 12),
                make_event("d1", "done", 8),
                make_event("d2", "done", 11),
                make_event("s1", "sweep", 14),
            ],
        ),
        (
            "done-without-waiting",
            [make_event("d1", "done", 9), make_event("s1", "sweep", 7)],
        ),
        ("waiting-without-end", [make_event("w1", "waiting", 4)]),
        ("empty-evidence", []),
    )

    for label, entries in cases:
        oracle_elapsed, oracle_completed = times(scope, [row for _, _, row in entries])
        readings = [
            {
                "id": event_id,
                "tenant": row["tenant"],
                "delivery": row["delivery"],
                "step": row["step"],
                "run": row["run"],
                "relation": row["state"],
                "reason": event_id,
                "at": row["at"],
                "event_time": seconds,
            }
            for event_id, seconds, row in entries
            if row["state"] in ("waiting", "done")
        ]
        sweeps = [
            {"id": event_id, "run": row["run"], "event_time": seconds, "complete": True}
            for event_id, seconds, row in entries
            if row["state"] == "sweep"
        ]
        data = {
            "loop_active_run": [{"id": scope["run"]}],
            "loop_status_observation": readings,
            "loop_sweep": sweeps,
        }
        _, derived, _ = evaluate(model, data)
        pack_elapsed = {int(row[-1]) for row in derived["delivery_waiting_time"] if row[:4] == key}
        pack_completed = {row[-1] for row in derived["delivery_completed_at"] if row[:4] == key}
        assert pack_elapsed == ({oracle_elapsed} if oracle_elapsed is not None else set()), label
        assert pack_completed == ({oracle_completed} if oracle_completed is not None else set()), label
