"""Check questions over a partial derived predicate against the shared expression vector."""

import json
from pathlib import Path
import subprocess

import pytest


class PartialCallMismatch(AssertionError):
    """The question checker or evaluator disagreed with the authored predicate outcomes."""


def test_expression_ask_partial_call():
    probe = Path(__file__).with_name("expression-ask-partial-call.mts")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, encoding="utf-8")
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        raise PartialCallMismatch(json.dumps(differences, indent=2))
