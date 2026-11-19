"""Turn a task ref listing and its push activity into dated claim observations."""
from importlib.util import find_spec

import pytest

T = 1_800_000_000  # 2027-01-15T08:00:00Z
A, B, C, D, OLD = (letter * 40 for letter in "abcde")


def ref(name, sha):
    return {"ref": f"refs/heads/{name}", "node_id": "n", "url": "https://example.org/ref",
            "object": {"sha": sha, "type": "commit", "url": "https://example.org/commit"}}


def push(after, timestamp):
    return {"id": 1, "before": "0" * 40, "after": after, "ref": "refs/heads/x", "timestamp": timestamp,
            "activity_type": "push", "actor": {"login": "someone"}}


REFS = [
    ref("task/b", B), ref("task/a", A), ref("task/c", C), ref("task/d", D),
    ref("golf1/planner-kring", OLD), ref("task", OLD), ref("tasks/other", OLD),
]
ACTIVITY = {
    "refs/heads/task/a": [push(A, "2027-01-15T04:00:00Z"), push(OLD, "2027-01-14T04:00:00Z")],
    "refs/heads/task/b": [push(OLD, "2027-01-15T06:00:00Z")],
    "refs/heads/task/c": [],
    "refs/heads/task/d": [push(D, "2027-01-15T06:30:00+02:00")],
}


def test_build_claim_capture():
    assert find_spec("loop.build_claim_capture") is not None, "The claim capture adapter is missing"
    from loop.build_claim_capture import claim_rows

    rows = claim_rows(REFS, ACTIVITY, run="current", observed_at=T, source="ref-listing",
                      activity_source="push-activity")
    claims = [{"id": f"task/{name}", "run": "current", "branch": f"task/{name}", "generation": sha,
               "observed_at": T, "source": "ref-listing"} for name, sha in (("a", A), ("b", B), ("c", C), ("d", D))]

    def pushed(name, after, at):
        return {"id": f"task/{name}@{after}@{at}", "claim": f"task/{name}", "after": after, "pushed_at": at,
                "source": "push-activity"}

    # Every push record is a candidate with its own source; the rules, not the adapter, pick the latest.
    activity = [
        pushed("a", OLD, T - 28 * 3600),
        pushed("a", A, T - 4 * 3600),
        pushed("b", OLD, T - 2 * 3600),
        pushed("d", D, T - 3 * 3600 - 1800),
    ]
    assert rows == {"build_claim": claims, "build_claim_activity": activity}
    assert claim_rows(list(reversed(REFS)), {name: list(reversed(records)) for name, records in
                                             reversed(list(ACTIVITY.items()))},
                      run="current", observed_at=T, source="ref-listing", activity_source="push-activity") == rows

    for bad_refs, bad_activity in (
        ([ref("task/a", "A" * 40)], {}),
        ([ref("task/a", A)], {"refs/heads/task/a": [push(A, "2027-01-15T04:00:00")]}),
        ([ref("task/a", A), ref("task/a", B)], {}),
        # A fractional second has no exact integer push time; truncating it would start the lease early.
        ([ref("task/a", A)], {"refs/heads/task/a": [push(A, "2027-01-15T03:59:59.5Z")]}),
    ):
        with pytest.raises(ValueError):
            claim_rows(bad_refs, bad_activity, run="current", observed_at=T, source="ref-listing",
                       activity_source="push-activity")


def test_build_claim_capture_keeps_whole_seconds_exact():
    """A whole-second timestamp in any offset converts to the exact Unix second."""
    from loop.build_claim_capture import claim_rows

    for stamp in ("2027-01-15T08:00:00Z", "2027-01-15T08:00:00.000000+00:00", "2027-01-15T09:00:00+01:00"):
        rows = claim_rows([ref("task/a", A)], {"refs/heads/task/a": [push(A, stamp)]}, run="current",
                          observed_at=T, source="ref-listing", activity_source="push-activity")
        assert [row["pushed_at"] for row in rows["build_claim_activity"]] == [T], stamp
