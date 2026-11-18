import pytest

from case_support import engine, imported, verified


def test_standard_time():
    imported("std-time")
    verified("end_not_recorded", ("support",))
    leaves = verified("judgement", ("support", "day-three", "unknown", "end_not_recorded"))
    assert any("support" in k for _, k in leaves)
    assert any("day-three" in k for _, k in leaves)
