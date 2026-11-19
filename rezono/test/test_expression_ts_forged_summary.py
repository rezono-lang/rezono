"""Check that TypeScript refuses a forged predicate summary, as Python lowering does."""

import json
from pathlib import Path
import subprocess

import pytest


class ForgedSummaryAccepted(AssertionError):
    """The native checker trusted a predicate summary linked for another relation or owner."""


@pytest.mark.xfail(
    strict=True,
    raises=ForgedSummaryAccepted,
    reason="Waits for PR #702 (fix/rezono-src-native-rule-check.ts-missing-predicate) to land, which changes the "
           "same negation check. Then add relation and owner to PredicateSummary and owner to the relation "
           "signature in rezono/src/native-rule-check.ts, and report R047 at the negation without related places "
           "when the summary names another relation or owner, as native_rule_lowering does for the `forged` case "
           "of tests/conformance/expression-negated-call.yaml. Read decisions/language-expression-semantics.md "
           "section 2.",
)
def test_expression_ts_forged_summary():
    probe = Path(__file__).with_name("expression-forged-summary.mts")
    result = subprocess.run(["node", str(probe)], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        assert all(difference["case"] != "genuine" for difference in differences), differences
        raise ForgedSummaryAccepted(json.dumps(differences, indent=2))
