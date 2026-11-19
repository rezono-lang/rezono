"""Check that TypeScript refuses a predicate summary that does not say where it was linked, as Python lowering does."""

import json
from pathlib import Path
import subprocess

import pytest


class MissingUnlinkedSummaryRefusal(AssertionError):
    """The native checker trusted a predicate summary without its relation, its owner or the signature's owner."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingUnlinkedSummaryRefusal,
    reason="extra: decisions/language-expression-semantics.md: In rezono/src/native-rule-check.ts, make relation and "
           "owner required on PredicateSummary and owner required on a derived relation's signature, and refuse a "
           "negation or group with R047 at the call and without related places when the summary leaves out its "
           "relation or owner, or the signature leaves out its owner, as native_rule_lowering does. Read section "
           "2, Linking partial predicates.",
)
def test_expression_ts_unlinked_summary():
    probe = Path(__file__).with_name("expression-unlinked-summary.mts")
    result = subprocess.run(["node", str(probe)], capture_output=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    differences = json.loads(result.stdout)
    assert isinstance(differences, list)
    if differences:
        assert all(difference["case"] != "genuine" for difference in differences), differences
        raise MissingUnlinkedSummaryRefusal(json.dumps(differences, indent=2))
