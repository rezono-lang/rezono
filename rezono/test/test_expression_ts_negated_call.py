"""Check the native TypeScript entry point against the shared linked rule vector."""

import json
from pathlib import Path
import subprocess

import pytest


class NegatedCallMismatch(AssertionError):
    """The native checker disagreed with the authored linked summaries."""


def test_expression_ts_negated_call():
    probe = Path(__file__).with_name("expression-negated-call.mts")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, encoding="utf-8")
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        raise NegatedCallMismatch(json.dumps(differences, indent=2))
