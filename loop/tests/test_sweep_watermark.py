"""Measure time from recorded event watermarks of the same run."""

import pytest

from wire_fixtures import entry


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/sweep_watermark.py. Measure time from recorded event watermarks of the same run.")
def test_sweep_watermark(monkeypatch):
    elapsed = entry(monkeypatch, "sweep_watermark", "elapsed")
    sweeps = [("r", "2030-01-01T10:02:00Z"), ("prior", "2031-01-01T10:02:00Z"),
              ("r", "2030-01-01T11:01:30+01:00")]
    assert elapsed("r", "2030-01-01T10:00:00Z", sweeps) == 120
    assert elapsed("missing", "2030-01-01T10:00:00Z", sweeps) is None
