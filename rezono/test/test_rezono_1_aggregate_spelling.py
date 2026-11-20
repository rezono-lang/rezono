"""One spelling per purpose for aggregates: in rezono 1 a positional relation call with `_` tests membership,
and counting, filtering and summing over a relation's rows use the tuple-set method form; the positional
aggregate is R028 there, while rezono 0 keeps it without W107
(decisions/language-rezono-1-aggregate-spelling.md, section 1)."""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at

ROOT = Path(__file__).resolve().parents[2]

# The three positional aggregates of decisions/language-native-rules.md, section 4, with the columns the subsidy
# examples declare: the slot `Application.household` (examples/subsidy-scheme/schema/subsidy.yaml),
# `line(application, cost_line, item, cents)` (examples/subsidy-scheme/rules/costs.dl) and
# `ledger_line(application, payment, cents)` (examples/subsidy/rules/ledger.dl).
COUNT = """\
rezono 1
pack sample
kind Household world closed
kind Application world closed
  household: Household
extend h: Household
  derived applications: Int = {aggregate}
"""

FILTERED_COUNT = """\
rezono 1
pack sample
kind Application world closed
kind CostItem world closed
kind CostLine world closed
  application: Application
  item: CostItem
  amount: Int
derived line(application: Application, cost_line: CostLine, item: CostItem, cents: Int): Bool = cost_line.application = application and cost_line.item = item and cost_line.amount = cents
extend a: Application
  derived has_quote: Bool = line(a, _, _, _)
  derived free_lines: Int = {aggregate}
"""

SUM = """\
rezono 1
pack sample
kind Application world closed
kind LedgerPayment world closed
  accepted: Bool
  application: Application
  amount: Int
derived ledger_line(application: Application, payment: LedgerPayment, cents: Int): Bool = payment.accepted and payment.application = application and payment.amount = cents
extend a: Application
  derived paid: Int = {aggregate}
"""

# (module, rezono 0 spelling, rezono 1 spelling, positional call, derived value, relation or kind)
CASES = [
    pytest.param(COUNT, "Application.household(_, h).count()", "Application.count(household = h)",
                 "Application.household(_, h)", "applications", "Application", id="count"),
    pytest.param(FILTERED_COUNT, "(line(a, _, _, _) where it.cents = 0).count()",
                 "line.count(application = a and cents = 0)", "line(a, _, _, _)", "free_lines", "line",
                 id="filtered-count"),
    pytest.param(SUM, "ledger_line(a, _, _).sum(it.cents)", "ledger_line.where(application = a).sum(cents)",
                 "ledger_line(a, _, _)", "paid", "ledger_line", id="sum"),
]

# The tuple-set spelling starts with the relation or kind name and `.where(` or the aggregate method.
TUPLE_SET_METHODS = ("where", "count", "sum", "min", "max", "any", "all", "none", "one")

REZONO_0 = """\
rezono 0
pack sample
rule household_applications(h: Household, n: Int) when h in Household and n = Application.household(_, h).count()
rule free_lines(a: Application, n: Int) when a in Application and n = (line(a, _, _, _) where it.cents = 0).count()
rule paid(a: Application, t: Int) when a in Application and t = ledger_line(a, _, _).sum(it.cents)
"""

WILD = {"wildcard": True}
REZONO_0_WHEN = {
    "household_applications": {"and": [
        {"in": [{"path": ["h"]}, {"kind": "Household"}]},
        {"cmp": ["=", {"path": ["n"]}, {"agg": ["count", {"call": ["Application.household", [WILD, {"path": ["h"]}]]}]}]},
    ]},
    "free_lines": {"and": [
        {"in": [{"path": ["a"]}, {"kind": "Application"}]},
        {"cmp": ["=", {"path": ["n"]}, {"agg": ["count", {"filter": [
            {"call": ["line", [{"path": ["a"]}, WILD, WILD, WILD]]},
            {"cmp": ["=", {"path": ["it", "cents"]}, {"lit": "0"}]},
        ]}]}]},
    ]},
    "paid": {"and": [
        {"in": [{"path": ["a"]}, {"kind": "Application"}]},
        {"cmp": ["=", {"path": ["t"]}, {"agg": ["sum", {"call": ["ledger_line", [{"path": ["a"]}, WILD, WILD]]},
                                                {"path": ["it", "cents"]}]}]},
    ]},
}

PROBE = """\
import { readFileSync } from 'node:fs';
import { moduleForm } from './rezono/src/module-json.ts';

const messages = JSON.parse(readFileSync('./rezono/messages/en.json', 'utf8'));
const sources = JSON.parse(process.argv[1]);
const render = (id, args = []) => (messages[id] ?? '').replace(/\\{(\\d+)\\}/g, (_m, i) => args[Number(i)] ?? '');
const out = sources.map((source) => {
  const { form, diagnostics } = moduleForm(source);
  return {
    format: form?.format ?? null,
    module: form?.module ?? null,
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


def read(*sources):
    """Per source, the module form's format and module (or None) and the diagnostics with rendered hints."""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", PROBE, json.dumps(list(sources))],
        cwd=ROOT,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    read_back = json.loads(result.stdout)
    assert isinstance(read_back, list) and len(read_back) == len(sources)
    return read_back


class MissingAggregateSpelling(AssertionError):
    """The rezono 1 reader did not refuse a positional aggregate with R028 and a tuple-set hint at the call, or did
    not read the tuple-set spelling beside a positional membership test."""


@pytest.mark.parametrize(("module", "positional", "tuple_set", "call", "derived", "relation"), CASES)
def test_rezono_1_refuses_positional_aggregates(module, positional, tuple_set, call, derived, relation):
    refused_source = module.format(aggregate=positional)
    accepted_source = module.format(aggregate=tuple_set)
    refused, accepted = read(refused_source, accepted_source)
    problems = []

    r028 = [d for d in refused["diagnostics"] if d["code"] == "R028"]
    if refused["format"] is not None or len(r028) != 1:
        problems.append({"positional_aggregate_not_refused_once": refused})
    else:
        [diagnostic] = r028
        want_span = at(refused_source, call, after=f"derived {derived}:")
        if diagnostic["span"] != want_span:
            problems.append({"r028_span": diagnostic["span"], "want": want_span})
        combined = " ".join([diagnostic["message"], diagnostic["hint"] or "", *diagnostic["args"]])
        if not any(f"{relation}.{method}(" in combined for method in TUPLE_SET_METHODS):
            problems.append({"r028_without_tuple_set_hint": diagnostic, "want_start": f"{relation}.where("})

    if accepted["diagnostics"] or accepted["format"] != "rezono.module/5" or accepted["module"] is None:
        problems.append({"tuple_set_spelling_not_read": accepted})

    if problems:
        raise MissingAggregateSpelling(json.dumps(problems, indent=2))


def test_rezono_0_keeps_positional_aggregates():
    """Counter-case: rezono 0 has no tuple-set form, so its positional aggregates keep their form and meaning,
    without W107 or any other diagnostic."""
    [read_back] = read(REZONO_0)
    assert read_back["diagnostics"] == [] and read_back["format"] == "rezono.module/3", read_back
    when = {decl["rule"]: decl.get("when") for decl in read_back["module"]["decls"]}
    assert when == REZONO_0_WHEN, json.dumps(when, indent=2)
