"""Counterexample tests for table priority handling of non-known row outcomes in compare-knowledge.ts and evaluate.ts."""

import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]

PROBE = """\
import { parseModule } from './rezono/src/module.ts';
import { compareAsKnown } from './rezono/src/compare-knowledge.ts';

const baseSrc = (extraFacts) => `rezono 0
pack sample
enum Tier = high | low
kind Item world closed
  a: Bool
  b: Bool
  derived tier: Tier
    table priority
      | a    | b    | -> tier |
      | true | -    | high    |
      | -    | true | low     |
fact Item
  | id | a     | b     |
  | i1 | true  | false |
  | i2 | false | true  |
${extraFacts}`;

function runCase(row0Lit, row1Lit, extraFacts) {
  const parsed = parseModule(baseSrc(extraFacts));
  const kindDecl = parsed.module.decls.find((d) => 'kind' in d && d.kind === 'Item');
  kindDecl.derived[0].table.rows[0].value = { lit: row0Lit };
  kindDecl.derived[0].table.rows[1].value = { lit: row1Lit };
  return compareAsKnown(parsed.module, {
    question: 'ask Item at 2026-06-01 where a or b show tier',
    beforeKnown: '2026-01-15',
    afterKnown: '2026-02-15',
  });
}

const out = {
  unknownVsLow: runCase(
    'unknown missing',
    'low',
    `fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
  ),
  invalidVsHigh: runCase(
    'invalid bad',
    'high',
    `fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
  ),
  unknownVsInvalid: runCase(
    'unknown missing',
    'invalid bad',
    `fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
`
  ),
  naVsLow: runCase(
    'n/a',
    'low',
    `fact item i1, valid 2026-01-01.., known 2026-02-01
  b = true
fact item i2, valid 2026-01-01.., known 2026-02-01
  a = unknown pending
`
  ),
};

process.stdout.write(JSON.stringify(out));
"""


def _run_probe():
    result = subprocess.run(
        ["node", "--input-type=module"],
        input=PROBE,
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_table_priority_does_not_swallow_unknown_or_invalid_outcomes():
    payload = _run_probe()

    # 1. Applying row with `unknown missing` must not be beaten by applying row with `low`,
    #    and undecided row with `unknown missing` output must block applying `low`.
    turns = {t["key"]: t for t in payload["unknownVsLow"]["turns"]}
    assert "i1" not in turns, f"low swallowed unknown missing: {turns.get('i1')}"
    assert "i2" in turns, "undecided row with unknown output must block applying low"
    assert turns["i2"]["before"]["values"]["tier"] == "low"
    assert turns["i2"]["after"]["states"]["tier"] == {"state": "unknown", "reason": "pending"}

    # 2. Applying row with `invalid bad` must not be beaten by applying row with `high` (rank 0),
    #    and undecided row with `invalid bad` output must block applying `high`.
    turns = {t["key"]: t for t in payload["invalidVsHigh"]["turns"]}
    assert "i1" not in turns, f"high swallowed invalid bad: {turns.get('i1')}"
    assert "i2" in turns, "undecided row with invalid output must block applying high"
    assert turns["i2"]["before"]["values"]["tier"] == "high"
    assert turns["i2"]["after"]["states"]["tier"] == {"state": "unknown", "reason": "pending"}

    # 3. Applying `unknown missing` + applying `invalid bad` must yield `invalid bad` (worstOf).
    turns = {t["key"]: t for t in payload["unknownVsInvalid"]["turns"]}
    assert "i1" in turns, "invalid row applying alongside unknown must turn state to invalid"
    assert turns["i1"]["before"]["states"]["tier"] == {"state": "unknown", "reason": "missing"}
    assert turns["i1"]["after"]["states"]["tier"] == {"state": "invalid", "reason": "bad"}

    # 4. Applying `n/a` propagates strictly per Appendix A.3 instead of being swallowed by `low`.
    turns = {t["key"]: t for t in payload["naVsLow"]["turns"]}
    assert "i1" not in turns, f"low swallowed n/a: {turns.get('i1')}"
    assert "i2" in turns, "undecided row with n/a output must block applying low"
    assert turns["i2"]["before"]["values"]["tier"] == "low"
    assert turns["i2"]["after"]["states"]["tier"] == {"state": "unknown", "reason": "pending"}
