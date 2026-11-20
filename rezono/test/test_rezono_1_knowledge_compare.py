"""Comparing an `ask` across two knowledge dates reuses `rezono.turns/1` to report changed rows
and the amended version that caused each turn (decisions/language-rezono-1.md, section 1)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

VERSIONED_MODULE = """\
rezono 1
pack sample
param rate: Int
  version 1, valid 2026-01-01..<2027-01-01, known 2026-01-15 = 10
  version 2 replaces 1, valid 2026-01-01..<2027-01-01, known 2026-03-01 = 15
kind Item world closed
  units: Int
  exempt: Bool
  derived fee: Int = units * rate
    unless exempt then 0
fact Item
  | id | units | exempt |
  | i1 | 4 | false |
  | i2 | 4 | true |
"""

PROBE = """\
let mod = null;
try {
  mod = await import('./rezono/src/compare-knowledge.ts');
} catch {
  mod = null;
}
if (!mod?.compareAsKnown) {
  process.stdout.write(JSON.stringify({ missing: true }));
} else {
  const source = process.argv[1];
  const result = mod.compareAsKnown(source, {
    question: 'ask Item at 2026-06-01 where fee >= 0 show fee',
    beforeKnown: '2026-02-01',
    afterKnown: '2026-03-15',
  });
  process.stdout.write(JSON.stringify({ missing: false, result }));
}
"""


class MissingKnowledgeDateComparison(AssertionError):
    """Two-knowledge-date comparison did not produce a rezono.turns/1 diff naming the turned rows and cause."""


def test_rezono_1_two_knowledge_date_comparison():
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, VERSIONED_MODULE],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    if payload.get("missing"):
        raise MissingKnowledgeDateComparison("missing rezono/src/compare-knowledge.ts exporting compareAsKnown")

    turns = payload["result"]
    problems = []
    if not isinstance(turns, dict) or turns.get("format") != "rezono.turns/1":
        problems.append({"bad_format": turns})
    else:
        rows = turns.get("turns", [])
        by_key = {row.get("key"): row for row in rows if isinstance(row, dict)}
        if "i1" not in by_key:
            problems.append({"missing_turned_row_i1": rows})
        elif by_key["i1"].get("before") == by_key["i1"].get("after") or not by_key["i1"].get("causes"):
            problems.append({"incomplete_turn_i1": by_key["i1"]})
        if "i2" in by_key:
            problems.append({"unchanged_exempt_item_i2_should_not_turn": by_key["i2"]})

    if problems:
        raise MissingKnowledgeDateComparison(json.dumps(problems, indent=2))
