"""Use observation event times for inclusive deadlines."""

from pathlib import Path
from runpy import run_path

import pytest


@pytest.mark.xfail(strict=True, reason="Read decisions/loop-design.md. Implement loop/event_deadline.py. Use observation event times for inclusive deadlines.")
def test_event_deadline():
    expired = run_path(str(Path(__file__).resolve().parents[1] / "event_deadline.py"))["expired"]
    start = "2030-03-03T13:40:00+02:00"
    assert not expired(start, "2030-03-03T11:40:29Z", 30)
    assert expired(start, "2030-03-03T11:40:30Z", 30)
    assert expired(start, "2030-03-03T11:40:31Z", 30)
