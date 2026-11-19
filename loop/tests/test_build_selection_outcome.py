"""Turn a build publication, or its absence, into a selection or full checks with the reason."""
from importlib.util import find_spec

import pytest

GREEN = {"checks": [{"name": "rezono:proofs", "status": "green"}, {"name": "rezono:schema", "status": "green"}]}


def rows(*keys):
    return [{"key": list(key)} for key in keys]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: Read decisions/build-reconciliation.md, sections Observed kinds and Selection and publication. Add "
        "loop/build_selection_outcome.py with selection_outcome(*, run, manifest, rows, engine_error) returning "
        "the mode, the selected suites and the full-selection reasons. The first failure decides: engine failure, "
        "missing publication, invalid publication (a check not green, no checks or a missing relation), then the "
        "published full-selection reasons. Write only in that file."
    ),
)
def test_build_selection_outcome():
    assert find_spec("loop.build_selection_outcome") is not None, "The build selection outcome glue is missing"
    from loop.build_selection_outcome import selection_outcome

    selected = {"build_selected_job": rows(("current", "beta", "change"), ("current", "alpha", "change"),
                                           ("current", "beta", "other")),
                "build_full_selection": []}
    assert selection_outcome(run="current", manifest=GREEN, rows=selected, engine_error=None) == {
        "mode": "selected", "suites": ["alpha", "beta"], "reasons": [],
    }
    assert selection_outcome(run="current", manifest=GREEN, rows={"build_selected_job": [],
                                                                  "build_full_selection": []},
                             engine_error=None) == {"mode": "selected", "suites": [], "reasons": []}

    def full(*reasons):
        return {"mode": "full", "suites": [], "reasons": list(reasons)}

    fallback = dict(selected, build_full_selection=rows(("current", "unmapped.txt"),
                                                       ("current", "missing-observation-receipt")))
    assert selection_outcome(run="current", manifest=GREEN, rows=fallback, engine_error=None) == full(
        "missing-observation-receipt", "unmapped.txt")
    red = {"checks": [{"name": "rezono:proofs", "status": "red"}, {"name": "rezono:schema", "status": "green"}]}
    assert selection_outcome(run="current", manifest=red, rows=selected, engine_error=None) == full(
        "invalid-publication")
    assert selection_outcome(run="current", manifest={"checks": []}, rows=selected, engine_error=None) == full(
        "invalid-publication")
    assert selection_outcome(run="current", manifest=None, rows=None, engine_error=None) == full(
        "missing-publication")
    assert selection_outcome(run="current", manifest=GREEN, rows=selected, engine_error="compile failed") == full(
        "engine-failure")
    # A relation the publication did not contain is unknown, not empty.
    assert selection_outcome(run="current", manifest=GREEN, rows={"build_selected_job": selected[
        "build_selected_job"]}, engine_error=None) == full("invalid-publication")

    with pytest.raises(ValueError):
        selection_outcome(run="current", manifest=GREEN, rows={
            "build_selected_job": rows(("previous", "beta", "change")), "build_full_selection": [],
        }, engine_error=None)
