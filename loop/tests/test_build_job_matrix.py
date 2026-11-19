"""Expand a verified suite selection to the configured job and shard matrix."""
from importlib.util import find_spec

import pytest

SUITES = [
    {"folder": "viewer", "kind": "node"},
    {"folder": "beta", "kind": "python", "total": 3},
    {"folder": "alpha", "kind": "python", "total": 1},
    {"folder": "contracts", "kind": "contracts", "total": 1},
]


def python(folder, kind, total):
    # The item shape of the existing ci-matrix command in scripts/components.py.
    return [{"folder": folder, "kind": kind, "shard": shard, "total": total,
             "label": folder if total == 1 else f"{folder} {shard + 1}/{total}"} for shard in range(total)]


def rows(*keys):
    return [{"key": list(key)} for key in keys]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/build-reconciliation.md, section Selection and publication. Add "
        "loop/build_job_matrix.py with job_matrix(*, run, selected, full, suites) that expands the verified "
        "build_selected_job and build_full_selection rows to the python and node matrix items of the ci-matrix "
        "command. Write only in that file."
    ),
)
def test_build_job_matrix():
    assert find_spec("loop.build_job_matrix") is not None, "The build job matrix glue is missing"
    from loop.build_job_matrix import job_matrix

    selected = rows(("current", "beta", "change"), ("current", "viewer", "change"), ("current", "beta", "other"))
    assert job_matrix(run="current", selected=selected, full=[], suites=SUITES) == {
        "python": python("beta", "python", 3),
        "node": [{"folder": "viewer", "kind": "node"}],
    }
    every = {
        "python": [*python("alpha", "python", 1), *python("beta", "python", 3),
                   *python("contracts", "contracts", 1)],
        "node": [{"folder": "viewer", "kind": "node"}],
    }
    assert job_matrix(run="current", selected=[], full=rows(("current", "unmapped.txt")), suites=SUITES) == every
    assert job_matrix(run="current", selected=selected, full=rows(("current", "missing-observation-receipt")),
                      suites=list(reversed(SUITES))) == every
    assert job_matrix(run="current", selected=[], full=[], suites=SUITES) == {"python": [], "node": []}

    for wrong in (
        {"selected": rows(("current", "gamma", "change")), "full": []},
        {"selected": rows(("previous", "beta", "change")), "full": []},
        {"selected": [], "full": rows(("previous", "unmapped.txt"))},
    ):
        with pytest.raises(ValueError):
            job_matrix(run="current", suites=SUITES, **wrong)
