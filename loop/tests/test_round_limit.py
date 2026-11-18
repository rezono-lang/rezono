"""Reject an exhausted run with pending steps while allowing success on the final round."""

from pathlib import Path
from runpy import run_path

import pytest


def test_round_limit():
    can_continue = run_path(str(Path(__file__).resolve().parents[1] / "round_limit.py"))["can_continue"]
    assert can_continue(used=1, limit=2, pending=["a"])
    assert not can_continue(used=2, limit=2, pending=[])
    with pytest.raises(ValueError, match="pending.*a"):
        can_continue(used=2, limit=2, pending=["a"])
    with pytest.raises(ValueError):
        can_continue(used=0, limit=0, pending=[])
