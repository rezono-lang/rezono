"""Count the planner queue from a complete pull listing, and nothing from an incomplete one."""
from importlib.util import find_spec

import pytest

T = 1_800_000_000


def pull(number, *, state="open", draft=False, base="main"):
    return {"number": number, "state": state, "draft": draft, "base": {"ref": base}, "head": {"ref": f"p{number}"}}


LISTING = [
    pull(1), pull(2), pull(3, draft=True), pull(4, base="release"), pull(5, state="closed"), pull(6),
]


RECEIPT = {"id": "pull-round", "run": "current", "event_time": T}


def test_build_queue_capture():
    assert find_spec("loop.build_queue_capture") is not None, "The queue reading adapter is missing"
    from loop.build_queue_capture import queue_reading

    expected = {"id": f"queue@{T}", "run": "current", "observed_at": T, "count": 3, "source": "pull-listing",
                "receipt": "pull-round"}
    assert queue_reading(LISTING, run="current", observed_at=T, source="pull-listing", receipt=RECEIPT,
                         base="main") == expected
    assert queue_reading(list(reversed(LISTING)), run="current", observed_at=T, source="pull-listing",
                         receipt=RECEIPT, base="main") == expected
    assert queue_reading([], run="current", observed_at=T, source="pull-listing", receipt=RECEIPT,
                         base="main") == dict(expected, count=0)
    with pytest.raises(ValueError):
        queue_reading([pull(1), pull(1)], run="current", observed_at=T, source="pull-listing", receipt=RECEIPT,
                      base="main")


@pytest.mark.parametrize("receipt", [
    None,
    dict(RECEIPT, run="other"),
    dict(RECEIPT, event_time=T - 1),
    dict(RECEIPT, id=""),
], ids=["missing", "other-run", "other-tick", "unnamed"])
def test_build_queue_capture_needs_completeness(receipt):
    """A listing is complete only with a receipt of the same run and cut, which the reading names."""
    from loop.build_queue_capture import queue_reading

    assert queue_reading(LISTING, run="current", observed_at=T, source="pull-listing", receipt=receipt,
                         base="main") is None


def without(key):
    def change(row):
        row = dict(row)
        del row[key]
        return row
    return change


@pytest.mark.parametrize("change", [
    lambda row: dict(row, draft=None),
    without("draft"),
    lambda row: dict(row, state=None),
    without("state"),
    lambda row: dict(row, base=None),
    lambda row: dict(row, base={}),
    without("number"),
], ids=["draft-none", "draft-missing", "state-none", "state-missing", "base-none", "base-ref-missing",
        "number-missing"])
def test_build_queue_capture_keeps_missing_fields_unknown(change):
    """A pull request without a readable state, draft flag, base or number leaves the count unknown."""
    from loop.build_queue_capture import queue_reading

    listing = [*LISTING[:-1], change(LISTING[-1])]
    assert queue_reading(listing, run="current", observed_at=T, source="pull-listing", receipt=RECEIPT,
                         base="main") is None
