"""Pack-embedded `example` blocks and W109 coverage reporting in rezono 1
(decisions/language-rezono-1.md, section 1; docs/rezono/v0.md, section 5e)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

PARTIAL_COVERAGE_MODULE = """\
rezono 1
pack sample
kind Item world closed
  amount: Int
  flagged: Bool
  derived fee: Int = amount * 2
    unless flagged then 0
check cap: Item.all(fee <= 100)
example "ordinary item pays double"
  given
    i1.amount = 10
    i1.flagged = false
  expect
    i1.fee = 20
example "high amount violates cap"
  given
    i2.amount = 60
    i2.flagged = false
  expect
    violation cap on i2
"""

FULL_COVERAGE_MODULE = PARTIAL_COVERAGE_MODULE + """\
example "flagged item pays zero"
  given
    i3.amount = 10
    i3.flagged = true
  expect
    i3.fee = 0
"""

PROBE = """\
import { moduleForm } from './rezono/src/module-json.ts';
import { printModule } from './rezono/src/print.ts';

const sources = JSON.parse(process.argv[1]);
const read = sources.map((source) => {
  const { form, diagnostics } = moduleForm(source);
  return {
    format: form?.format ?? null,
    module: form?.module ?? null,
    printed: form ? printModule(form.module) : null,
    diagnostics: diagnostics.map(({ code, span }) => ({ code, span })),
  };
});

let runner = null;
try {
  runner = await import('./rezono/src/examples.ts');
} catch {
  runner = null;
}

const coverage = runner?.runExamples
  ? read.map((entry) => (entry.module ? runner.runExamples(entry.module) : null))
  : null;

process.stdout.write(JSON.stringify({ read, coverage }));
"""


class MissingRezono1Examples(AssertionError):
    """The reader/runner did not parse, print, evaluate `example` blocks, or emit W109 for uncovered clauses."""


def test_rezono_1_example_blocks_and_w109_coverage():
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps([PARTIAL_COVERAGE_MODULE, FULL_COVERAGE_MODULE])],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    partial, full = payload["read"]
    problems = []

    for label, entry, src in (("partial", partial, PARTIAL_COVERAGE_MODULE), ("full", full, FULL_COVERAGE_MODULE)):
        if entry["diagnostics"] or entry["format"] != "rezono.module/5" or entry["module"] is None:
            problems.append({f"{label}_read": entry})
        elif entry["printed"] != src:
            problems.append({f"{label}_printed": entry["printed"], "want": src})

    if payload["coverage"] is None:
        problems.append("missing rezono/src/examples.ts exporting runExamples")
    else:
        partial_cov, full_cov = payload["coverage"]
        if not partial_cov or partial_cov.get("failures"):
            problems.append({"partial_failures": partial_cov})
        partial_codes = [w.get("code") for w in (partial_cov or {}).get("warnings", [])]
        if "W109" not in partial_codes:
            problems.append({"expected_w109_for_uncovered_unless": partial_cov})
        if not full_cov or full_cov.get("failures"):
            problems.append({"full_failures": full_cov})
        full_codes = [w.get("code") for w in (full_cov or {}).get("warnings", [])]
        if "W109" in full_codes:
            problems.append({"unexpected_w109_when_fully_covered": full_cov})

    if problems:
        raise MissingRezono1Examples(json.dumps(problems, indent=2))
