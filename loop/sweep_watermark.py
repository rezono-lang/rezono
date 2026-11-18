"""Measure event time through the latest recorded sweep of the active run."""

from collections.abc import Iterable
from datetime import datetime


def event_time(value: str) -> datetime:
    instant = datetime.fromisoformat(value)
    if instant.utcoffset() is None:
        raise ValueError("recorded event time requires a UTC offset")
    return instant


def elapsed(run: str, start: str, sweeps: Iterable[tuple[str, str]]) -> int | None:
    """Return whole seconds at the latest in-run watermark at or after start."""
    started = event_time(start)
    latest = max((event_time(at) for row_run, at in sweeps if row_run == run), default=None)
    if latest is None or latest < started:
        return None
    delta = latest - started
    return delta.days * 86400 + delta.seconds
