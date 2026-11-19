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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/build-claim-release.md section 1. Add loop/build_claim_pull_capture.py with "
        "pull_rows(claims, answers, *, observed_at, source) returning BuildClaimPullReading records. An answer "
        "that is missing, unreadable or does not match the open-pull query for that head yields no row. "
        "Write only in that file."
    ),
)
def test_build_claim_pull_capture():
    assert find_spec("loop.build_claim_pull_capture") is not None, "The pull reading adapter is missing"
    from loop.build_claim_pull_capture import pull_rows

    rows = pull_rows(CLAIMS, ANSWERS, observed_at=T, source="pull-query")
    assert rows == [
        {"id": f"task/none@{T}", "claim": "task/none", "observed_at": T, "state": "none", "source": "pull-query"},
        {"id": f"task/open@{T}", "claim": "task/open", "observed_at": T, "state": "open", "source": "pull-query"},
    ], f"Only a matching open answer or a complete empty answer is a reading: {rows}"
    assert pull_rows(list(reversed(CLAIMS)), dict(reversed(list(ANSWERS.items()))), observed_at=T,
                     source="pull-query") == rows
