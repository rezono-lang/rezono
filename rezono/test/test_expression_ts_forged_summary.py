"""Check that TypeScript refuses a forged predicate summary, as Python lowering does."""

import json
from pathlib import Path
import subprocess

import pytest


class ForgedSummaryAccepted(AssertionError):
    """The native checker trusted a predicate summary linked for another relation or owner."""


def test_expression_ts_forged_summary():
    probe = Path(__file__).with_name("expression-forged-summary.mts")
    result = subprocess.run(["node", str(probe)], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        assert all(difference["case"] != "genuine" for difference in differences), differences
        raise ForgedSummaryAccepted(json.dumps(differences, indent=2))
