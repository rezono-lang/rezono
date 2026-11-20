"""`world closed` written on a kind in a rezono 1 module gives W107 with the hint "leave it out", and the form keeps
the line as written (decisions/language-rezono-1-defaults.md, section 3). The sources, the span and the hint are
written from that decision; the hint's text is the English message of `hint.leave_out`."""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at

ROOT = Path(__file__).resolve().parents[2]

WRITTEN = """\
rezono 1
pack sample
kind Zone world closed
  name: Text
kind Team world open
  name: Text
"""

LEFT_OUT = """\
rezono 1
pack sample
kind Zone
  name: Text
kind Team world open
  name: Text
"""

# Counter-case: in rezono 0 the default is open, so writing `world closed` is no default and gives no warning.
REZONO_0 = WRITTEN.replace("rezono 1", "rezono 0", 1)

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
    module: form?.module ?? null,
    printed: form ? printModule(form.module) : null,
    diagnostics: diagnostics.map((d) => ({
      code: d.code,
      hint: d.hint ? render(d.hint.id, d.hint.args) : null,
      span: d.span,
    })),
  };
});
process.stdout.write(JSON.stringify(out));
"""


def kinds(read):
    return {decl["kind"]: decl for decl in read["module"]["decls"] if "kind" in decl}


class MissingWorldLineHint(AssertionError):
    """The reader did not warn at `world closed` on a rezono 1 kind, warned elsewhere, or changed the form."""


@pytest.mark.xfail(
    strict=True,
    raises=MissingWorldLineHint,
    reason="M3: decisions/language-rezono-1-defaults.md: Waits for "
           "compiler/tests/rezono/test_rezono_1_world_default.py--test_rezono_1_kind_without_world_lowers_closed and "
           "for a planner to remove `world closed` from the rezono 1 source of rezono/test/test_rezono_1_examples.py. "
           "In rezono/src/, give W107 with the hint `hint.leave_out` at the words `world closed` on a kind line of a "
           "rezono 1 module; keep `world: closed` in the form and its printed text as written; give no warning for a "
           "kind without the line, for `world open`, or in rezono 0. Read section 3.",
)
def test_rezono_1_world_closed_gives_w107():
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps([REZONO_0, WRITTEN, LEFT_OUT])],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    rezono_0, written, left_out = json.loads(result.stdout)

    # Counter-case: rezono 0 reads `world closed` without a warning and keeps it in the form, as today.
    assert rezono_0["diagnostics"] == [] and rezono_0["module"] is not None, rezono_0
    assert kinds(rezono_0)["Zone"].get("world") == "closed", rezono_0["module"]

    problems = []
    want = [{"code": "W107", "hint": "leave it out", "span": at(WRITTEN, "world closed")}]
    if written["module"] is None or written["format"] != "rezono.module/5" or written["diagnostics"] != want:
        problems.append({"written": written, "want": want})
    else:
        if kinds(written)["Zone"].get("world") != "closed" or kinds(written)["Team"].get("world") != "open":
            problems.append({"written form": written["module"]})
        if written["printed"] != WRITTEN:
            problems.append({"written printed": written["printed"], "want": WRITTEN})
    if left_out["module"] is None or left_out["format"] != "rezono.module/5" or left_out["diagnostics"]:
        problems.append({"left out": left_out})
    else:
        if "world" in kinds(left_out)["Zone"] or kinds(left_out)["Team"].get("world") != "open":
            problems.append({"left out form": left_out["module"]})
        if left_out["printed"] != LEFT_OUT:
            problems.append({"left out printed": left_out["printed"], "want": LEFT_OUT})
    if problems:
        raise MissingWorldLineHint(json.dumps(problems, indent=2))
