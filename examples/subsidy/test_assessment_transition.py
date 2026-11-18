"""The handwritten first scenario changes one assessment and supplies its income."""

from pathlib import Path

from rules_support import states


def test_one_received_statement_changes_one_assessment():
    # In facts/applications.yaml, A003 already has a quote and belongs to H003.
    # Scenario 1 adds a single statement for H003 with income 2730000.
    _, _, run = states(Path(__file__).parent)
    before, after = run[:2]
    assert (before.label, after.label) == ("0-applications", "1-income-received")
    old, new = before.derived, after.derived
    assert old["assessment"] - new["assessment"] == {("A003", "unknown", "income_statement_not_received")}
    assert new["assessment"] - old["assessment"] == {("A003", "known", "")}
    assert new["assessed_income"] - old["assessed_income"] == {("A003", "2730000")}
    assert old["assessed_income"] <= new["assessed_income"]
