import pytest

from offline_cases import PLAN_HASH, relation


def test_cleanup_policy():
    facts = {"sweep": [("clear",), ("occupied",), ("incomplete",)],
             "sweep__plan_hash": [(s, PLAN_HASH) for s in ("clear", "occupied", "incomplete")],
             "sweep__coverage": [("clear", "complete"), ("occupied", "complete")],
             "resource__sweep": [("a", "clear"), ("b", "occupied"), ("c", "occupied")],
             "resource__plan_hash": [("a", "b" * 64), ("b", PLAN_HASH)]}
    # Historical rows remain readable. None records a dispatch or page response.
    assert relation("cleanup", facts, "cleaned") == set()
