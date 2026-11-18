"""Check the published decision date against the run's recorded UTC cut."""

from datetime import UTC, datetime

import pytest

from test_build_selection import OBSERVED_AT, capture, published, repository
from test_build_task_order import task_observations


@pytest.mark.parametrize(("case", "dates", "allowed"), [
    ("correct", (("current", 20270115),), True),
    ("wrong", (("current", 20270116),), False),
    ("conflicting", (("current", 20260115), ("current", 20270115)), False),
    ("foreign", (("current", 20270115), ("foreign", 20260115)), True),
    ("duplicate-day", (("current", 20270115), ("current", 20270115)), True),
])
def test_build_placement_requires_the_unique_utc_date(tmp_path, case, dates, allowed):
    assert datetime.fromtimestamp(OBSERVED_AT, UTC).isoformat() == "2027-01-15T08:00:00+00:00"
    base, head, paths = repository(tmp_path / "source", "decisions/task-policy.md")
    data = capture(tmp_path / "source", base, head, paths)
    task_observations(data, [(OBSERVED_AT, 29)])
    data["reference_date"] = []
    data["build_policy_date"] = []
    for index, (run, day) in enumerate(dates):
        reference = f"reference-{index}"
        data["reference_date"].append({"id": reference, "title": "Policy date", "day": day})
        data["build_policy_date"].append({
            "id": f"binding-{index}", "run": run, "reference": reference, "observed_at": OBSERVED_AT,
        })
        if run == "foreign":
            data["build_run"].append({**data["build_run"][0], "id": run, "receipt": "foreign-receipt"})
            data["loop_sweep_receipt"].append({"id": "foreign-receipt", "run": run, "event_time": OBSERVED_AT})

    rows = published(tmp_path, data)
    actual = {
        relation: [row["key"][1:] for row in rows[relation] if row["key"][0] == "current"]
        for relation in ("build_task_precedes", "build_planner_slot", "build_planner_waiting")
    }
    assert actual == {
        "build_task_precedes": [["task-language", "task-core"]] if allowed else [],
        "build_planner_slot": [["queue-0", "placement-policy"]] if allowed else [],
        "build_planner_waiting": [] if allowed else [["queue-policy-unknown"]],
    }, case
