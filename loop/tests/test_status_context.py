"""Separate tenant and commit status histories."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/delivery-commit-status.md. Implement loop/status_context.py. Separate tenant and commit status histories.")
def test_status_context():
    context = run_path(str(Path(__file__).resolve().parents[1] / "status_context.py"))["context"]
    commit = "a" * 40
    assert context(commit, "elm", "elm-1", "database") == (commit, "rezono/delivery/elm/elm-1/database")
    assert context(commit, "reed", "reed-1", "database") == (commit, "rezono/delivery/reed/reed-1/database")
    for invalid in ("elm/other", "", "-elm"):
        with pytest.raises(ValueError):
            context(commit, invalid, "elm-1", "database")
