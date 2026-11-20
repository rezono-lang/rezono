"""Language version switch in the reader: rezono 0 and rezono 1 side by side, rezono.module/5,
and R028 refusals for removed rezono 0 constructs including table priority with `table first` hint
(decisions/language-rezono-1.md, sections 1, 3.2 and 5.8)."""

import json
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]

REZONO_0_TABLE_PRIORITY = """\
rezono 0
pack sample
enum Level = low | high
kind Item world closed
  flag: Bool
  derived tier: Level
    table priority
      | flag | -> tier |
      | true | high |
      | - | low |
"""

REZONO_0_NATIVE_RULE = """\
rezono 0
pack sample
kind Item world closed
rule listed(item: Item) when item in Item
"""

REZONO_1_BASIC = """\
rezono 1
pack sample
kind Item world closed
  active: Bool
  derived flagged: Bool = active
"""

REZONO_1_TABLE_PRIORITY = """\
rezono 1
pack sample
enum Level = low | high
kind Item world closed
  flag: Bool
  derived tier: Level
    table priority
      | flag | -> tier |
      | true | high |
      | - | low |
"""

REZONO_1_LEGACY_RULE = """\
rezono 1
pack sample
kind Item world closed
rule listed(item: Item) when item in Item
"""

REZONO_1_PIPE_BLOCK = """\
rezono 1
pack sample
rules legacy
  | .decl listed(item: symbol)
"""

PROBE = """\
import { readFileSync } from 'node:fs';
import { moduleForm } from './rezono/src/module-json.ts';
import { printModule } from './rezono/src/print.ts';

const messages = JSON.parse(readFileSync('./rezono/messages/en.json', 'utf8'));
const sources = JSON.parse(process.argv[1]);
const render = (id, args = []) => (messages[id] ?? '').replace(/\\{(\\d+)\\}/g, (_m, i) => args[Number(i)] ?? '');
const out = sources.map((source) => {
  const { form, diagnostics } = moduleForm(source);
  return {
    format: form?.format ?? null,
    rezono: form?.module?.rezono ?? null,
    printed: form ? printModule(form.module) : null,
    diagnostics: diagnostics.map((d) => ({
      code: d.code,
      args: d.args ?? [],
      message: render(d.code, d.args),
      hint: d.hint ? render(d.hint.id, d.hint.args) : null,
      span: d.span,
    })),
  };
});
process.stdout.write(JSON.stringify(out));
"""


class MissingRezono1VersionSwitch(AssertionError):
    """The reader did not dispatch rezono 0 vs rezono 1, emit rezono.module/5, or refuse removed forms with R028."""


def test_rezono_1_version_switch():
    sources = [
        REZONO_0_TABLE_PRIORITY,
        REZONO_0_NATIVE_RULE,
        REZONO_1_BASIC,
        REZONO_1_TABLE_PRIORITY,
        REZONO_1_LEGACY_RULE,
        REZONO_1_PIPE_BLOCK,
    ]
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps(sources)],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    r0_table, r0_rule, r1_basic, r1_priority, r1_rule, r1_pipe = json.loads(result.stdout)

    # Counter-cases: rezono 0 modules stay valid with their existing formats and canonical print.
    assert r0_table["diagnostics"] == [] and r0_table["format"] == "rezono.module/1", r0_table
    assert r0_table["printed"] == REZONO_0_TABLE_PRIORITY
    assert r0_rule["diagnostics"] == [] and r0_rule["format"] == "rezono.module/3", r0_rule
    assert r0_rule["printed"] == REZONO_0_NATIVE_RULE

    problems = []
    if r1_basic["diagnostics"] or r1_basic["format"] != "rezono.module/5" or r1_basic["rezono"] != "1":
        problems.append({"rezono_1_basic": r1_basic})
    elif r1_basic["printed"] != REZONO_1_BASIC:
        problems.append({"rezono_1_basic_printed": r1_basic["printed"], "want": REZONO_1_BASIC})

    r028_priority = [d for d in r1_priority["diagnostics"] if d["code"] == "R028"]
    if r1_priority["format"] is not None or not r028_priority:
        problems.append({"rezono_1_table_priority": r1_priority})
    else:
        combined = " ".join(
            [r028_priority[0]["message"], r028_priority[0]["hint"] or "", *r028_priority[0]["args"]]
        )
        if "table first" not in combined:
            problems.append({"rezono_1_table_priority_missing_hint": r028_priority[0]})

    for label, read in (("rezono_1_legacy_rule", r1_rule), ("rezono_1_pipe_block", r1_pipe)):
        if read["format"] is not None or "R028" not in [d["code"] for d in read["diagnostics"]]:
            problems.append({label: read})

    if problems:
        raise MissingRezono1VersionSwitch(json.dumps(problems, indent=2))
