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

    rows = claim_rows(REFS, ACTIVITY, run="current", observed_at=T, source="ref-listing")
    claims = [{"id": f"task/{name}", "run": "current", "branch": f"task/{name}", "generation": sha,
               "observed_at": T, "source": "ref-listing"} for name, sha in (("a", A), ("b", B), ("c", C), ("d", D))]
    # Only the newest push is evidence; a newest push to another commit is kept as observed.
    activity = [
        {"id": f"task/a@{A}", "claim": "task/a", "after": A, "pushed_at": T - 4 * 3600, "source": "ref-listing"},
        {"id": f"task/b@{OLD}", "claim": "task/b", "after": OLD, "pushed_at": T - 2 * 3600, "source": "ref-listing"},
        {"id": f"task/d@{D}", "claim": "task/d", "after": D, "pushed_at": T - 3 * 3600 - 1800,
         "source": "ref-listing"},
    ]
    assert rows == {"build_claim": claims, "build_claim_activity": activity}
    assert claim_rows(list(reversed(REFS)), dict(reversed(list(ACTIVITY.items()))), run="current", observed_at=T,
                      source="ref-listing") == rows

    for bad_refs, bad_activity in (
        ([ref("task/a", "A" * 40)], {}),
        ([ref("task/a", A)], {"refs/heads/task/a": [push(A, "2027-01-15T04:00:00")]}),
        ([ref("task/a", A), ref("task/a", B)], {}),
    ):
        with pytest.raises(ValueError):
            claim_rows(bad_refs, bad_activity, run="current", observed_at=T, source="ref-listing")
