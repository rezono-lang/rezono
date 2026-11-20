"""The `otherwise` operator (`a otherwise b`) for conflict-safe fallback on `n/a`, and warning `W115` when
`unless` guards on `x is known` where `x` can be `invalid`
(decisions/language-rezono-1-refinements.md, section 2)."""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at

ROOT = Path(__file__).resolve().parents[2]

OTHERWISE_MODULE = """\
rezono 1
pack sample
enum Flag
  yes
  no
kind Function
kind Product
kind Release
  product: Product
  stable: Flag
  released_on_day: Int
kind Service
  product: Product
kind Choice
  service: Service
  function: Function
  provider: Service
kind Pin
  service: Service
  release: Release
derived asks(s: Service, f: Function): Bool = Service.any(it = s) and Function.any(it = f)
derived provides(s: Service, f: Function, port: Int): Bool = Service.any(it = s) and Function.any(it = f) and port = 443
derived chosen(a: Service, f: Function): Service?
  over asks(a, f)
  = Choice.where(service = a and function = f).one(provider)
derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = chosen(a, f) otherwise Service.where(provides(it, f, _)).one()
extend p: Product
  derived newest_day: Int? = Release.where(product = p and stable = yes).max(released_on_day)
extend s: Service
  derived pin: Release? = Pin.where(service = s).one(release)
  derived runs: Release = pin otherwise Release.where(it.product = s.product and stable = yes and released_on_day = s.product.newest_day).one()
  derived chained: Release = pin otherwise pin otherwise Release.where(it.product = s.product).one()
"""

UNLESS_IS_KNOWN_WARNS = """\
rezono 1
pack sample
kind Function
kind Service
kind Choice
  service: Service
  function: Function
  provider: Service
derived asks(s: Service, f: Function): Bool = Service.any(it = s) and Function.any(it = f)
derived provides(s: Service, f: Function, port: Int): Bool = Service.any(it = s) and Function.any(it = f) and port = 443
derived chosen(a: Service, f: Function): Service?
  over asks(a, f)
  = Choice.where(service = a and function = f).one(provider)
derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = Service.where(provides(it, f, _)).one()
  unless chosen(a, f) is known then chosen(a, f)
"""

UNLESS_NOT_NA_CLEAN = """\
rezono 1
pack sample
kind Function
kind Service
kind Choice
  service: Service
  function: Function
  provider: Service
derived asks(s: Service, f: Function): Bool = Service.any(it = s) and Function.any(it = f)
derived provides(s: Service, f: Function, port: Int): Bool = Service.any(it = s) and Function.any(it = f) and port = 443
derived chosen(a: Service, f: Function): Service?
  over asks(a, f)
  = Choice.where(service = a and function = f).one(provider)
derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = Service.where(provides(it, f, _)).one()
  unless not (chosen(a, f) is n/a) then chosen(a, f)
"""

UNLESS_NON_INVALID_SLOT_CLEAN = """\
rezono 1
pack sample
kind Item
  override_val: Int?
  base_val: Int
extend x: Item
  derived effective: Int = base_val
    unless override_val is known then override_val
"""

MODULE_PROBE = """\
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
  const printed = checked.form ? rezono.printModule(checked.form.module) : null;
  const reparsed = printed ? rezono.moduleForm(printed) : null;
  return {
    format: checked.form?.format ?? null,
    module: checked.form?.module ?? null,
    printed,
    roundtrip_ok: Boolean(reparsed && !reparsed.diagnostics.length && JSON.stringify(reparsed.form?.module) === JSON.stringify(checked.form?.module)),
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

EVAL_PROBE = """\
import { answer, check, isError, load } from './rezono/src/index.ts';

const schema = {
  rezono: '1.0',
  pack: 'sample',
  base: 'https://example.org/sample/',
  kinds: {
    Item: {
      world: 'closed',
      id: { type: 'Text' },
      slots: {
        primary: { type: 'Integer', card: '?', states: ['known', 'not_applicable', 'unknown', 'invalid'] },
        fallback: { type: 'Integer', card: '?', states: ['known', 'not_applicable', 'unknown', 'invalid'] },
        label: { type: 'Text', card: '1', states: ['known'] },
      },
    },
  },
};

const rows = [
  { $kind: 'Item', $id: 'i-known', primary: 10, fallback: { $invalid: 'unused_conflict' }, label: 'ok' },
  { $kind: 'Item', $id: 'i-na-known', primary: { $na: '' }, fallback: 20, label: 'ok' },
  { $kind: 'Item', $id: 'i-na-na', primary: { $na: '' }, fallback: { $na: '' }, label: 'ok' },
  { $kind: 'Item', $id: 'i-na-unknown', primary: { $na: '' }, fallback: { $unknown: 'no_fallback' }, label: 'ok' },
  { $kind: 'Item', $id: 'i-na-invalid', primary: { $na: '' }, fallback: { $invalid: 'bad_fallback' }, label: 'ok' },
  { $kind: 'Item', $id: 'i-unknown', primary: { $unknown: 'missing_primary' }, fallback: 30, label: 'ok' },
  { $kind: 'Item', $id: 'i-invalid', primary: { $invalid: 'multiple_values' }, fallback: 40, label: 'ok' },
];

const data = load(schema, rows);
const q = 'ask Item where (primary otherwise fallback) > 0 show primary otherwise fallback';
const checked = check(q, schema);
const mismatch = check('ask Item where (primary otherwise label) is known', schema);

let evaluated = null;
if (!checked.diagnostics.some(isError)) {
  const ans = await answer(checked, schema, data);
  evaluated = {
    rows: ans.rows.map((r) => [r.$id, r.c1]),
    undecided: ans.undecided.map((u) => [u.$id, u.state, u.reason]),
    not_applicable: ans.counts.not_applicable,
  };
}

process.stdout.write(JSON.stringify({
  check_diagnostics: checked.diagnostics.map((d) => ({ code: d.code, span: d.span })),
  mismatch_codes: mismatch.diagnostics.map((d) => d.code),
  evaluated,
}));
"""


def run_node(script, *args):
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script, *args],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class MissingOtherwiseOperator(AssertionError):
    """`otherwise` syntax/AST/round-trip or W115 on `unless x is known` is missing or wrong."""


class MissingOtherwiseEvaluation(AssertionError):
    """Four-state evaluation or typechecking of `a otherwise b` in rezono/src/ is missing or wrong."""


def test_rezono_1_otherwise_syntax_and_w115():
    payload = run_node(
        MODULE_PROBE,
        json.dumps([OTHERWISE_MODULE, UNLESS_IS_KNOWN_WARNS, UNLESS_NOT_NA_CLEAN, UNLESS_NON_INVALID_SLOT_CLEAN]),
    )
    if "missing_export" in payload:
        raise MissingOtherwiseOperator(json.dumps(payload, indent=2))
    with_otherwise, warns, not_na_clean, slot_clean = payload["results"]
    problems = []

    if with_otherwise["diagnostics"] or with_otherwise["format"] != "rezono.module/5" or not with_otherwise["roundtrip_ok"]:
        problems.append({"otherwise_module_failed": with_otherwise})
    else:
        decls = {d["derived"]: d for d in with_otherwise["module"]["decls"] if isinstance(d.get("derived"), str)}
        needs_val = decls.get("needs", {}).get("value")
        if not (isinstance(needs_val, dict) and isinstance(needs_val.get("otherwise"), list) and len(needs_val["otherwise"]) == 2):
            problems.append({"needs_ast_not_otherwise": needs_val})
        ext = [d for d in with_otherwise["module"]["decls"] if d.get("extend") == "Service"]
        chained = next((m["value"] for e in ext for m in e.get("derived", []) if m.get("derived") == "chained"), None)
        if not (isinstance(chained, dict) and isinstance(chained.get("otherwise"), list)
                and isinstance(chained["otherwise"][1], dict) and "otherwise" in chained["otherwise"][1]):
            problems.append({"chained_not_right_associative": chained})

    w115 = [d for d in warns["diagnostics"] if d["code"] == "W115"]
    if warns["format"] != "rezono.module/5" or len(w115) != 1:
        problems.append({"expected_one_w115_warning": warns})
    else:
        want_span = at(UNLESS_IS_KNOWN_WARNS, "chosen(a, f) is known", after="unless ")
        if w115[0]["span"] != want_span:
            problems.append({"w115_span": w115[0]["span"], "want": want_span})
        if "otherwise" not in (w115[0]["hint"] or ""):
            problems.append({"w115_hint_missing_otherwise": w115[0]})

    if [d for d in not_na_clean["diagnostics"] if d["code"] == "W115"]:
        problems.append({"unexpected_w115_on_not_na": not_na_clean})

    if [d for d in slot_clean["diagnostics"] if d["code"] == "W115"]:
        problems.append({"unexpected_w115_on_non_invalid_slot": slot_clean})

    if problems:
        raise MissingOtherwiseOperator(json.dumps(problems, indent=2))


def test_otherwise_four_state_evaluation():
    result = run_node(EVAL_PROBE)
    problems = []
    if result["check_diagnostics"]:
        problems.append({"check_failed": result["check_diagnostics"]})
    if "R003" not in result["mismatch_codes"]:
        problems.append({"type_mismatch_not_r003": result["mismatch_codes"]})
    want = {
        "rows": [["i-known", "10"], ["i-na-known", "20"]],
        "undecided": [
            ["i-invalid", "invalid", "multiple_values"],
            ["i-na-invalid", "invalid", "bad_fallback"],
            ["i-na-unknown", "unknown", "no_fallback"],
            ["i-unknown", "unknown", "missing_primary"],
        ],
        "not_applicable": 1,
    }
    if result["evaluated"] != want:
        problems.append({"evaluated": result["evaluated"], "want": want})
    if problems:
        raise MissingOtherwiseEvaluation(json.dumps(problems, indent=2))
