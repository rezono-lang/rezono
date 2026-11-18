"""Evaluate replay deadlines using recorded event times."""

from datetime import datetime, timedelta


def expired(start: str, watermark: str, seconds: int) -> bool:
    """Return whether the recorded watermark reached the inclusive deadline."""
    started_at = datetime.fromisoformat(start)
    observed_at = datetime.fromisoformat(watermark)
    if started_at.tzinfo is None or observed_at.tzinfo is None:
        raise ValueError("Deadline event timestamps require UTC offsets")
    return observed_at - started_at >= timedelta(seconds=seconds)
