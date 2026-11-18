"""Require an accepted proposal and its immutable full commit identifier."""

from pathlib import Path
from runpy import run_path

import pytest


def test_status_target():
    target = run_path(str(Path(__file__).resolve().parents[1] / "status_target.py"))["target"]
    sha = "ab" * 20
    assert target({"accepted": True, "commit": sha, "branch": "topic"}) == sha
    assert target({"accepted": False, "commit": sha}) is None
    for ref in ("topic", sha[:7], ""):
        with pytest.raises(ValueError):
            target({"accepted": True, "commit": ref})
