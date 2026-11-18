"""Filter evidence by authenticated tenant before publication."""

from pathlib import Path
from runpy import run_path

import pytest


def test_status_visibility():
    visible = run_path(str(Path(__file__).resolve().parents[1] / "status_visibility.py"))["visible"]
    elm = {"tenant": "elm", "step": "db", "evidence": "e1"}
    reed = {"tenant": "reed", "step": "db", "evidence": "r1"}
    assert list(visible("elm", [reed, elm])) == [elm]
    assert list(visible("reed", [elm, reed])) == [reed]
    assert list(visible("unknown", [elm, reed])) == []
