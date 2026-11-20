"""Checking and applying a whole-record suppose insertion `+ Kind key {slot = value, ...}`
(decisions/language-safe-steps.md, section 1)."""

import json
from pathlib import Path
import subprocess

import pytest


class MissingSupposeInsertRowEvaluation(AssertionError):
    """rezono/src/check.ts or rezono/src/evaluate.ts did not check or apply a whole-record insertion."""


def test_suppose_insert_row_evaluate():
    probe = Path(__file__).with_name("suppose-insert-row-evaluate.mts")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, encoding="utf-8")
    issues = json.loads(result.stdout)
    assert isinstance(issues, list)
    if issues:
        raise MissingSupposeInsertRowEvaluation(json.dumps(issues, indent=2))
