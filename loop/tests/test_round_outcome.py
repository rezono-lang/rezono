"""Differentiate clean completion, waiting, terminal drift and blocking evidence."""

from pathlib import Path
from runpy import run_path

import pytest


def test_round_outcome():
    outcome = run_path(str(Path(__file__).resolve().parents[1] / "round_outcome.py"))["outcome"]
    assert outcome(declared=[], done=[], stuck=[], drift=[]) == "success"
    assert outcome(declared=["a"], done=[], stuck=[], drift=[]) == "pending"
    assert outcome(declared=["a"], done=["a"], stuck=[], drift=[]) == "success"
    assert outcome(declared=["a"], done=["a"], stuck=[], drift=["mismatch"]) == "failure"
    assert outcome(declared=["a"], done=[], stuck=["a"], drift=[]) == "failure"
