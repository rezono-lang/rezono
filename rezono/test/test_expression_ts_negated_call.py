"""Check the native TypeScript entry point against the shared linked rule vector."""

import json
from pathlib import Path
import subprocess

import pytest


class NegatedCallMismatch(AssertionError):
    """The native checker disagreed with the authored linked summaries."""


@pytest.mark.xfail(
    strict=True,
    raises=NegatedCallMismatch,
    reason="Apply supplied linked predicate states to negated native calls in checkNativeRules. "
           "Use the shared expression-negated-call vector and decisions/language-expression-semantics.md §2. "
           "The frozen summaries make this independent of the linker and Python lowering.",
)
def test_expression_ts_negated_call():
    probe = Path(__file__).with_name("expression-negated-call.mts")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, encoding="utf-8")
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        raise NegatedCallMismatch(json.dumps(differences, indent=2))
