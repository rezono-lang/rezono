"""Check that TypeScript refuses a predicate summary that does not say where it was linked, as Python lowering does."""

import json
from pathlib import Path
import subprocess

import pytest


class MissingUnlinkedSummaryRefusal(AssertionError):
    """The native checker trusted a predicate summary without its relation, its owner or the signature's owner."""


def test_expression_ts_unlinked_summary():
    probe = Path(__file__).with_name("expression-unlinked-summary.mts")
    result = subprocess.run(["node", str(probe)], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        assert all(difference["case"] != "genuine" for difference in differences), differences
        raise MissingUnlinkedSummaryRefusal(json.dumps(differences, indent=2))
