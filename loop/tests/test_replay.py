"""Replay the two-round hand-calculated trace through the executor without a cluster."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Waits for test_frontier and test_round_outcome. Integrate the executor in loop/replay.py. Replay the two-round hand-calculated trace through the executor without a cluster.")
def test_replay():
    replay = run_path(str(Path(__file__).resolve().parents[1] / "replay.py"))["replay"]
    requirements = {"build": [], "serve": ["artifact"]}
    completion = {"build": "artifact", "serve": "available"}
    sweeps = [[("r", "artifact", "built")], [("r", "available", "up")]]
    observed = [("prior", "artifact", "old-artifact")]
    assert replay("r", requirements, completion, observed, sweeps, 2) == ([["build"], ["serve"]], "success")
