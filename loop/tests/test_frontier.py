"""Emit plans only for ready steps in stable order and deduplicate witnesses."""

from pathlib import Path
from runpy import run_path

import pytest


def test_frontier():
    frontier = run_path(str(Path(__file__).resolve().parents[1] / "frontier.py"))["frontier"]
    plans = {"b": "plan-b", "a": "plan-a", "c": "plan-c"}
    rows = [("r", "b", "b1"), ("r", "a", "a1"), ("r", "b", "b2"), ("old", "c", "old-c")]
    assert list(frontier("r", rows, plans)) == ["plan-a", "plan-b"]
    assert list(frontier("r", reversed(rows), plans)) == ["plan-a", "plan-b"]
    assert list(frontier("unknown", rows, plans)) == []
