"""Read one pull request answer per claim branch, and nothing from an unreadable answer."""
from importlib.util import find_spec

import pytest

T = 1_800_000_000


def claim(branch):
    return {"id": branch, "run": "current", "branch": branch, "generation": "a" * 40, "observed_at": T,
            "source": "ref-listing"}


def pull(number, branch, state="open"):
    return {"number": number, "state": state, "draft": False, "head": {"ref": branch, "sha": "b" * 40},
            "base": {"ref": "main"}}


CLAIMS = [claim(f"task/{name}") for name in ("open", "none", "unreadable", "missing", "foreign", "closed")]
ANSWERS = {
    "task/open": [pull(7, "task/open")],
    "task/none": [],
    "task/unreadable": None,
    "task/foreign": [pull(8, "task/other")],
    "task/closed": [pull(9, "task/closed", state="closed")],
}


RECEIPT = {"id": "pull-round", "run": "current", "event_time": T}


def test_build_claim_pull_capture():
    assert find_spec("loop.build_claim_pull_capture") is not None, "The pull reading adapter is missing"
    from loop.build_claim_pull_capture import pull_rows

    rows = pull_rows(CLAIMS, ANSWERS, observed_at=T, source="pull-query", receipt=RECEIPT)
    assert rows == [
        {"id": f"task/none@{T}", "claim": "task/none", "observed_at": T, "state": "none", "source": "pull-query",
         "receipt": "pull-round"},
        {"id": f"task/open@{T}", "claim": "task/open", "observed_at": T, "state": "open", "source": "pull-query"},
    ], f"Only a matching open answer or a complete empty answer is a reading: {rows}"
    assert pull_rows(list(reversed(CLAIMS)), dict(reversed(list(ANSWERS.items()))), observed_at=T,
                     source="pull-query", receipt=RECEIPT) == rows


@pytest.mark.parametrize("receipt", [
    None,
    dict(RECEIPT, run="other"),
    dict(RECEIPT, event_time=T - 1),
    dict(RECEIPT, id=""),
], ids=["missing", "other-run", "other-tick", "unnamed"])
def test_build_claim_pull_capture_needs_completeness(receipt):
    """An empty answer is evidence of no pull request only with a receipt of the complete read at this cut."""
    from loop.build_claim_pull_capture import pull_rows

    rows = pull_rows(CLAIMS, ANSWERS, observed_at=T, source="pull-query", receipt=receipt)
    assert rows == [
        {"id": f"task/open@{T}", "claim": "task/open", "observed_at": T, "state": "open", "source": "pull-query"},
    ], f"An empty answer without a matching completeness receipt must stay unknown: {rows}"
