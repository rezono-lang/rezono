"""Check the published decision date against the run's recorded UTC cut."""

from datetime import UTC, datetime

import pytest

from rezono_compiler import facts
from test_build_selection import OBSERVED_AT, capture, published, repository
from test_build_task_order import planner_listings, task_observations


def _iso_date(day: int) -> str:
    return f"{day // 10000:04d}-{day // 100 % 100:02d}-{day % 100:02d}"


@pytest.mark.parametrize(("case", "dates", "allowed"), [
    ("correct", (("current", 20270115),), True),
    ("wrong", (("current", 20270116),), False),
    ("conflicting", (("current", 20260115), ("current", 20270115)), False),
    ("missing", (), False),
    ("foreign", (("current", 20270115), ("foreign", 20260115)), True),
    ("duplicate-day", (("current", 20270115), ("current", 20270115)), True),
])
def test_build_placement_requires_the_unique_utc_date(tmp_path, case, dates, allowed):
    assert datetime.fromtimestamp(OBSERVED_AT, UTC).isoformat() == "2027-01-15T08:00:00+00:00"
    base, head, paths = repository(tmp_path / "source", "decisions/task-policy.md")
    data = capture(tmp_path / "source", base, head, paths)
    task_observations(data)
    evidence = planner_listings(data, [(OBSERVED_AT, 29, True)])
    data["reference_date"] = []
    data["build_policy_date"] = []
    for index, (run, day) in enumerate(dates):
        reference = f"reference-{index}"
        data["reference_date"].append({"id": reference, "title": "Policy date", "date": _iso_date(day), "day": day})
        data["build_policy_date"].append({
            "id": f"binding-{index}", "run": run, "reference": reference, "observed_at": OBSERVED_AT,
        })
        if run == "foreign":
            data["build_run"].append({**data["build_run"][0], "id": run, "receipt": "foreign-receipt"})
            data["loop_sweep_receipt"].append({"id": "foreign-receipt", "run": run, "event_time": OBSERVED_AT})

    rows = published(tmp_path, data, evidence)
    actual = {
        relation: [row["key"][1:] for row in rows[relation] if row["key"][0] == "current"]
        for relation in ("build_task_precedes", "build_planner_slot", "build_planner_waiting")
    }
    assert actual == {
        "build_task_precedes": [["task-language", "task-core"]] if allowed else [],
        "build_planner_slot": [["queue-0", "placement-policy"]] if allowed else [],
        "build_planner_waiting": [] if allowed else [["queue-policy-unknown"]],
    }, case


def test_build_policy_date_follows_the_utc_calendar(tmp_path):
    base, head, paths = repository(tmp_path / "source", "decisions/task-policy.md")
    data = capture(tmp_path / "source", base, head, paths)
    sample = data["build_run"][0]
    epoch = datetime(1970, 1, 1, tzinfo=UTC)

    def tick(year, month, day, hour=0, minute=0, second=0):
        delta = datetime(year, month, day, hour, minute, second, tzinfo=UTC) - epoch
        return delta.days * 86400 + delta.seconds

    expected = set()
    cases = [
        ("first-supported", tick(1900, 1, 1), 19000101, True),
        ("before-epoch", -1, 19691231, True),
        ("at-epoch", 0, 19700101, True),
        ("leap-century", tick(2000, 2, 29, 23, 59, 59), 20000229, True),
        ("after-midnight", tick(2000, 3, 1), 20000301, True),
        ("previous-day", tick(2000, 3, 1), 20000229, False),
        ("ordinary-century-end", tick(2100, 2, 28, 23, 59, 59), 21000228, True),
        ("ordinary-century", tick(2100, 3, 1), 21000301, True),
        ("ordinary-century-previous", tick(2100, 3, 1), 21000228, False),
        ("last-supported", tick(9999, 12, 31, 23, 59, 59), 99991231, True),
        ("earlier-than-supported", tick(1900, 1, 1) - 1, 19000101, False),
        ("latest-integer", 2**63 - 1, 99991231, False),
        ("earliest-integer", -(2**63), 19000101, False),
    ]
    for run, instant, day, valid in cases:
        data["build_run"].append({**sample, "id": run, "observed_at": instant, "receipt": run})
        data["loop_sweep_receipt"].append({"id": run, "run": run, "event_time": instant})
        data.setdefault("reference_date", []).append(
            {"id": run, "title": "Policy date", "date": _iso_date(day), "day": day}
        )
        data.setdefault("build_policy_date", []).append({
            "id": run, "run": run, "reference": run, "observed_at": instant,
        })
        if valid:
            expected.add((run, run))

    data["build_policy_date"].append({
        "id": "stale", "run": "at-epoch", "reference": "before-epoch", "observed_at": -1,
    })
    rows = published(tmp_path / "valid", data)
    assert {tuple(row["key"]) for row in rows["build_policy_date_at_cut"]} == expected

    # A non-leap-year 29 February is refused at admission as an invalid calendar date.
    invalid = capture(tmp_path / "source", base, head, paths)
    invalid["reference_date"] = [{"id": "invalid-february", "title": "Policy date", "date": "2100-02-29", "day": 21000229}]
    invalid["build_policy_date"] = [
        {"id": "invalid-february", "run": "current", "reference": "invalid-february", "observed_at": OBSERVED_AT}
    ]
    with pytest.raises(facts.LoadError):
        published(tmp_path / "invalid-february", invalid)
