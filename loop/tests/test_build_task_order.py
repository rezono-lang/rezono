"""Publish task and planner decisions through the real loop and decision libraries."""
import pytest

from test_build_selection import OBSERVED_AT, capture, published, repository


def task_observations(data, readings):
    run = "current"
    tasks = ("language", "core", "waiting", "declined")
    data.update({
        "loop_active_run": [{"id": run}],
        "loop_step": [{"id": task, **({"precedes": ["waiting"]} if task == "core" else {})} for task in tasks],
        "loop_completion": [
            {"id": "core-evidence", "run": run, "step": "core", "token": "compiled-core", "reason": "compile-result"}
        ],
        "loop_expectation": [{"id": "compiled-core", "value": "passed"}],
        "loop_refusal": [{"id": "decline", "run": run, "step": "declined", "reason": "terminal-refusal"}],
        "build_task": [
            {"id": "task-" + task, "run": run, "step": task,
             "track": "core" if task == "core" else "language", "source": "task-board"}
            for task in tasks
        ],
        "reference_date": [{"id": "policy-day", "title": "Observed reference day", "day": 20270115}],
        "build_policy_date": [
            {"id": "policy-cut", "run": run, "reference": "policy-day", "observed_at": OBSERVED_AT}
        ],
        "decision": [
            {"id": "placement-policy", "title": "Build placement", "state": "in_force",
             "valid_from": "2027-01-01", "valid_from_day": 20270101, "decider": ["build-policy"]}
        ],
        "build_track_rank": [
            {"id": "language-first", "decision": "placement-policy", "track": "language", "rank": 0},
            {"id": "core-next", "decision": "placement-policy", "track": "core", "rank": 1},
        ],
        "build_queue_limit": [{"id": "planner-limit", "decision": "placement-policy", "limit": 30}],
        "build_queue_reading": [
            {"id": f"queue-{index}", "run": run, "observed_at": tick, "count": count, "source": "queue-reader",
             **({"receipt": receipt} if receipt else {})}
            for index, (tick, count, receipt) in enumerate(readings)
        ],
    })


@pytest.mark.parametrize(("readings", "waiting_reason"), [
    ([(OBSERVED_AT, 29, "receipt")], None),
    ([(OBSERVED_AT, 30, "receipt")], "queue-limit"),
    ([(OBSERVED_AT - 1, 29, "receipt")], "queue-evidence-unknown"),
    ([(OBSERVED_AT, 29, "receipt"), (OBSERVED_AT, 30, "receipt")], "queue-evidence-unknown"),
    # A count without a receipt of its complete listing does not prove planner capacity.
    ([(OBSERVED_AT, 29, None)], "queue-evidence-unknown"),
])
def test_build_task_order_and_planner_limit(tmp_path, readings, waiting_reason):
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/task-policy.md")
    records = capture(source, base, head, paths)
    task_observations(records, readings)
    rows = published(tmp_path, records)

    assert {row["key"][1] for row in rows["build_task_ready"]} == {"task-language", "task-core"}
    assert [row["key"][:3] for row in rows["build_task_waiting"]] == [["current", "task-waiting", "compiled-core"]]
    assert {row["key"][1] for row in rows["build_task_stuck"]} == {"task-declined"}
    assert [row["key"] for row in rows["build_task_precedes"]] == [["current", "task-language", "task-core"]]
    assert [row["key"] for row in rows["build_planner_slot"]] == (
        [["current", "queue-0", "placement-policy"]] if waiting_reason is None else []
    )
    assert [row["key"] for row in rows["build_planner_waiting"]] == (
        [["current", waiting_reason]] if waiting_reason is not None else []
    )
