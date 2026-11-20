"""Set-only collections in rezono 1: silent multiset path projection over a collection (`S.slot` where `S` is a set)
is refused with `R028` and `hint.use_instead`, and `.one([expr])` accepts an optional projection expression;
`rezono 0` keeps its existing collection-path behavior unchanged
(decisions/language-rezono-1-refinements.md, section 3.3)."""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at, read_modules

ROOT = Path(__file__).resolve().parents[2]

BASE_SCHEMA = """\
rezono 1
pack sample
kind Spec
  nodes: Int
kind Group
  tag: Text
kind Item
  group: Group
kind Entry
  item: Item
  spec: Spec
  qty: Int
extend Item
  entries: Entry* inverse Entry.item
kind Choice
  item: Item
  group: Group
  target: Item
"""

CASES = [
    pytest.param(
        BASE_SCHEMA + "extend x: Item\n  derived total: Int = entries.spec.nodes.sum()\n",
        "entries.spec.nodes",
        "entries.sum(spec.nodes)",
        BASE_SCHEMA + "extend x: Item\n  derived total: Int = entries.sum(spec.nodes)\n",
        id="sum-path-over-set",
    ),
    pytest.param(
        BASE_SCHEMA + "extend x: Item\n  derived peak: Int? = entries.spec.nodes.max()\n",
        "entries.spec.nodes",
        "entries.max(spec.nodes)",
        BASE_SCHEMA + "extend x: Item\n  derived peak: Int? = entries.max(spec.nodes)\n",
        id="max-path-over-set",
    ),
    pytest.param(
        BASE_SCHEMA + "extend g: Group\n  derived n: Int = Item.group.count()\n",
        "Item.group",
        "Item.count()",
        BASE_SCHEMA + "extend g: Group\n  derived n: Int = Item.count()\n",
        id="count-path-over-set",
    ),
    pytest.param(
        BASE_SCHEMA
        + "derived asks(a: Item, g: Group): Bool = a.group = g\n"
        + "derived chosen(a: Item, g: Group): Item?\n"
        + "  over asks(a, g)\n"
        + "  = Choice.where(item = a and group = g).target.one()\n",
        "Choice.where(item = a and group = g).target",
        "Choice.where(item = a and group = g).one(target)",
        BASE_SCHEMA
        + "derived asks(a: Item, g: Group): Bool = a.group = g\n"
        + "derived chosen(a: Item, g: Group): Item?\n"
        + "  over asks(a, g)\n"
        + "  = Choice.where(item = a and group = g).one(target)\n",
        id="one-path-over-set",
    ),
]

REZONO_0_COLLECTION_PATH = """\
rezono 0
pack sample
kind Group world closed
kind Item world closed
  group: Group?
  flag: Bool
extend Item
  derived peers: Int = (Item where flag).group.count()
"""

PROBE = """\
import { readFileSync } from 'node:fs';
import * as rezono from './rezono/src/index.ts';

const messages = JSON.parse(readFileSync('./rezono/messages/en.json', 'utf8'));
const render = (id, args = []) => (messages[id] ?? '').replace(/\\{(\\d+)\\}/g, (_m, i) => args[Number(i)] ?? '');
const sources = JSON.parse(process.argv[1]);
const checkModule = rezono.checkModule;
if (typeof checkModule !== 'function') {
  process.stdout.write(JSON.stringify({ missing_export: 'checkModule' }));
  process.exit(0);
}
const out = sources.map((source) => {
  const checked = checkModule(source);
  return {
    format: checked.form?.format ?? null,
    diagnostics: checked.diagnostics.map((d) => ({
      code: d.code,
      args: d.args ?? [],
      message: render(d.code, d.args),
      hint: d.hint ? render(d.hint.id, d.hint.args) : null,
      span: d.span,
    })),
  };
});
process.stdout.write(JSON.stringify({ results: out }));
"""


def check_sources(*sources):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps(list(sources))],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class MissingCollectionProjectionRefusal(AssertionError):
    """rezono 1 did not refuse collection path projection with R028 + hint or did not accept the explicit form."""


@pytest.mark.parametrize(("refused_source", "bad_expr", "hint_text", "accepted_source"), CASES)
def test_rezono_1_refuses_collection_path_projection(refused_source, bad_expr, hint_text, accepted_source):
    payload = check_sources(refused_source, accepted_source)
    if "missing_export" in payload:
        raise MissingCollectionProjectionRefusal(json.dumps(payload, indent=2))
    refused, accepted = payload["results"]
    problems = []

    r028 = [d for d in refused["diagnostics"] if d["code"] == "R028"]
    if len(r028) != 1:
        problems.append({"expected_single_r028": refused})
    else:
        want_span = at(refused_source, bad_expr, after="derived ")
        if r028[0]["span"] != want_span:
            problems.append({"r028_span": r028[0]["span"], "want": want_span})
        if hint_text not in (r028[0]["hint"] or ""):
            problems.append({"r028_hint_mismatch": r028[0], "want_hint": hint_text})

    if accepted["diagnostics"] or accepted["format"] != "rezono.module/5":
        problems.append({"accepted_form_failed": accepted})

    if problems:
        raise MissingCollectionProjectionRefusal(json.dumps(problems, indent=2))


def test_rezono_0_keeps_collection_path_projection():
    """Counter-case: rezono 0 modules keep collection path projections without R028 or W107."""
    [read_back] = read_modules(REZONO_0_COLLECTION_PATH)
    assert read_back["diagnostics"] == [] and read_back["format"] == "rezono.module/1", read_back
