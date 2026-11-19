"""Count the planner queue from a complete pull listing, and nothing from an incomplete one."""
from importlib.util import find_spec

import pytest

T = 1_800_000_000


def pull(number, *, state="open", draft=False, base="main"):
    return {"number": number, "state": state, "draft": draft, "base": {"ref": base}, "head": {"ref": f"p{number}"}}


LISTING = [
    pull(1), pull(2), pull(3, draft=True), pull(4, base="release"), pull(5, state="closed"), pull(6),
]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/build-claim-release.md section 4. Add loop/build_queue_capture.py with "
        "queue_reading(pulls, *, run, observed_at, source, complete, base) returning one BuildQueueReading "
        "record or None. Write only in that file."
    ),
)
def test_build_queue_capture():
    assert find_spec("loop.build_queue_capture") is not None, "The queue reading adapter is missing"
    from loop.build_queue_capture import queue_reading

    expected = {"id": f"queue@{T}", "run": "current", "observed_at": T, "count": 3, "source": "pull-listing"}
    assert queue_reading(LISTING, run="current", observed_at=T, source="pull-listing", complete=True,
                         base="main") == expected
    assert queue_reading(list(reversed(LISTING)), run="current", observed_at=T, source="pull-listing",
                         complete=True, base="main") == expected
    assert queue_reading([], run="current", observed_at=T, source="pull-listing", complete=True,
                         base="main") == dict(expected, count=0)
    assert queue_reading(LISTING, run="current", observed_at=T, source="pull-listing", complete=False,
                         base="main") is None
    with pytest.raises(ValueError):
        queue_reading([pull(1), pull(1)], run="current", observed_at=T, source="pull-listing", complete=True,
                      base="main")
