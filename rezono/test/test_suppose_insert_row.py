"""A suppose line can insert a whole record: `+ Kind key {slot = value, ...}` (decisions/language-safe-steps.md,
section 1). The expected trees are copied from that decision; the other suppose forms keep their trees."""

import json

import pytest

from question_probe import read_questions

RECORD = '+ Policy policy-a {mode = "enforce", zone = Zone:`zone-a`}'
INSERTED = {"insert_row": {"kind": "Policy", "key": "policy-a", "slots": [
    {"name": "mode", "value": {"lit": '"enforce"'}},
    {"name": "zone", "value": {"lit": "Zone:`zone-a`"}},
]}}


class MissingSupposeInsertRow(AssertionError):
    """The question reader did not read or print a whole-record insertion as the decision gives it."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingSupposeInsertRow,
    reason="extra: decisions/language-safe-steps.md: Read `+ Kind key {slot = value, ...}` as a suppose line "
           "{insert_row: {kind, key, slots: [{name, value}]}} in the Suppose rule of rezono/src/grammar.ts and "
           "rezono/src/parse.ts, add it to the Suppose type of rezono/src/tree.ts, and print it in "
           "rezono/src/print-expression.ts with one space around each = and after each comma, the fields in "
           "authored order. Read section 1, Insert a complete record with suppose. Checking it against the schema "
           "and applying it are not part of this test.",
)
def test_suppose_insert_row():
    # Counter-case: the existing suppose forms keep their trees, before and after.
    kept = read_questions("- Policy policy-a", '+ policy-a.mode = "audit"', "- policy-a.mode")
    assert [r["question"] for r in kept] == [
        {"retract_row": ["Policy", "policy-a"]},
        {"set": [{"path": ["policy-a", "mode"]}, {"lit": '"audit"'}]},
        {"retract": {"path": ["policy-a", "mode"]}},
    ], kept

    tight, empty = read_questions('+ Policy policy-a {mode="enforce",zone=Zone:`zone-a`}', "+ Policy policy-b {}")
    expected = [(tight, INSERTED, RECORD), (empty, {"insert_row": {"kind": "Policy", "key": "policy-b", "slots": []}},
                                            "+ Policy policy-b {}")]
    for read, tree, printed in expected:
        if read["diagnostics"] or read["question"] != tree or read["printed"] != printed:
            raise MissingSupposeInsertRow(json.dumps(read, indent=2))
