"""Only complete observation sweeps produce absence evidence."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/sweep_absence.py. Only complete observation sweeps produce absence evidence.")
def test_sweep_absence(monkeypatch):
    absence = entry(monkeypatch, "sweep_absence", "absence")
    desired = {"echo": "desired/echo", "peer": "desired/peer"}
    present = {"echo": "observed/echo"}
    assert absence("r", "sweep-1", False, desired, present) == []
    assert absence("r", "sweep-1", True, desired, present) == [
        ("r", "peer", "desired/peer", "sweep-1")]
    assert absence("r", "sweep-1", True, desired, {**present, "peer": "seen"}) == []
