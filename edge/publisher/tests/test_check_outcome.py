"""The publisher reads the outcome of every check from the compiled program and decides no status itself
(decisions/integrity-checks-as-rules.md, "The publisher reads the outcome")."""

import re
from pathlib import Path

import pytest

BATCH = Path(__file__).resolve().parents[1] / "rezono_publisher" / "batch.py"
# A count of violations or a status chosen from one: the three ways batch.py decided a check itself.
COUNTING = re.compile(r'COUNT\(|"red" if|len\(derived\.get\(')


def test_the_pattern_finds_a_count():
    """The test below can fail: the pattern finds each way of counting it guards against."""
    for line in ('n = con.execute(f"SELECT COUNT(*) FROM {v}")', '{"status": "red" if n else "green"}',
                 "n = len(derived.get(name, ()))"):
        assert COUNTING.search(line), line


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/integrity-checks-as-rules.md: Waits for compiler/tests/test_integrity_rules.py--"
        "test_value_range_violations_are_invariant_rows_with_witnesses. Then the compiler emits the view "
        "check_outcome(name, violations, status) with one row per check of the manifest (every logical check, "
        "every invariant, every check view of rezono_compiler.rules_sql.checks), zero rows included, status red "
        "exactly when violations is greater than zero; and edge/publisher/rezono_publisher/batch.py copies its "
        "rows into the manifest's checks instead of counting validation_result, the invariants and the rule "
        "check views itself."
    ),
)
def test_the_publisher_counts_no_violations():
    assert [m.group(0) for m in COUNTING.finditer(BATCH.read_text("utf-8"))] == []
