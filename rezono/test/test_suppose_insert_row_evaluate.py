"""Checking and applying a whole-record suppose insertion `+ Kind key {slot = value, ...}`
(decisions/language-safe-steps.md, section 1)."""

import json
from pathlib import Path
import subprocess

import pytest


class MissingSupposeInsertRowEvaluation(AssertionError):
    """rezono/src/check.ts or rezono/src/evaluate.ts did not check or apply a whole-record insertion."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingSupposeInsertRowEvaluation,
    reason="extra: decisions/language-safe-steps.md: In rezono/src/check.ts and rezono/src/evaluate.ts, check and "
           "apply a whole-record insertion `+ Kind key {slot = value, ...}` instead of refusing it with R015 and "
           "throwing in suppose(): validate the kind, required slots, slot names, duplicate slots, read-only "
           "inverse/identifier slots and slot types/cardinalities, allow empty braces when no non-id slot is "
           "required, enforce freshness against existing keys in data, and return a new Data without mutating the "
           "input. Read section 1, Insert a complete record with suppose. Note: rezono/test/suppose-insert-row-evaluate.mts "
           "line 56 expects {$ref: 'zone-a'}, whereas answer() formats reference columns as "
           "{$ref: '<pack>@<schemaId>:Zone/zone-a'} per rezono/src/evaluate.ts toJson and docs/rezono/expressions.md §8a.",
)
def test_suppose_insert_row_evaluate():
    probe = Path(__file__).with_name("suppose-insert-row-evaluate.mts")
    result = subprocess.run(["node", str(probe)], check=True, capture_output=True, encoding="utf-8")
    issues = json.loads(result.stdout)
    assert isinstance(issues, list)
    if issues:
        raise MissingSupposeInsertRowEvaluation(json.dumps(issues, indent=2))
