"""Project a step from matching run evidence."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/delivery-commit-status.md. Implement loop/status_projection.py. Project a step from matching run evidence.")
def test_status_projection():
    project = run_path(str(Path(__file__).resolve().parents[1] / "status_projection.py"))["project"]
    step = {"tenant": "elm", "delivery": "elm-1", "step": "database", "run": "new"}
    old = {**step, "run": "old", "relation": "done", "reason": "old-observation"}
    applied = {**step, "relation": "applied", "reason": "dispatch"}
    other = {**step, "tenant": "reed", "relation": "done", "reason": "other-owner"}
    assert project(step, [old, applied, other]) == "pending"
    assert project(step, [{**step, "relation": "done", "reason": "observed"}]) == "success"
    assert project(step, [{**step, "relation": "stuck", "reason": "expired"}]) == "failure"
