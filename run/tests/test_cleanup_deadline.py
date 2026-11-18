import pytest

from offline_cases import relation


def test_cleanup_deadline():
    facts = {"attempt": [(x,) for x in ("late", "early", "clean", "planned", "unknown")],
             "attempt__state": [("late", "applied"), ("early", "applied"), ("clean", "cleaned"),
                                ("planned", "planned"), ("unknown", "applied")],
             "attempt__deadline_us": [(x, 100) for x in ("late", "early", "clean", "planned", "unknown")],
             "attempt__watermark_us": [("late", 100), ("early", 99), ("clean", 105), ("planned", 102)]}
    assert relation("cleanup-deadline", facts, "overdue") == {("late",)}
