"""Schema-building and declaration coverage in `checkModule` for rezono 1:
- `d.over` and `d.table` in `derived` declarations;
- `step` and `example` declarations;
- transitive kind inheritance (`kind Child is Base`) with cycle guard;
- currency symbols populated from module unit/money declarations.
"""

import json
from pathlib import Path
import subprocess

import pytest
from reader_probe import at

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
  qty: Int
kind Entry
  item: Item
  spec: Spec
extend Item
  entries: Entry* inverse Entry.item
"""

PROBE = """\
import { readFileSync } from 'node:fs';
import * as rezono from './rezono/src/index.ts';

const messages = JSON.parse(readFileSync('./rezono/messages/en.json', 'utf8'));
const render = (id, args = []) => (messages[id] ?? '').replace(/\\{(\\d+)\\}/g, (_m, i) => args[Number(i)] ?? '');
const sources = JSON.parse(process.argv[1]);
const out = sources.map((source) => {
  const checked = rezono.checkModule(source);
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
    return json.loads(result.stdout)["results"]


def test_check_module_checks_derived_over_domain():
    unknown_over = BASE_SCHEMA + """\
derived score(a: Item, g: Group): Int
  over missing_domain(a, g)
  = a.qty
"""
    wrong_arg_order = BASE_SCHEMA + """\
derived asks(a: Item, g: Group): Bool = a.group = g
derived score(a: Item, g: Group): Int
  over asks(g, a)
  = a.qty
"""
    non_bool_domain = BASE_SCHEMA + """\
derived asks(a: Item, g: Group): Bool = a.group = g
derived weight(a: Item, g: Group): Int
  over asks(a, g)
  = a.qty
derived score(a: Item, g: Group): Int
  over weight(a, g)
  = a.qty
"""
    open_kind_domain = """\
rezono 1
pack sample
kind OpenItem world open
  qty: Int
derived score(a: OpenItem): Int
  over OpenItem(a)
  = a.qty
"""
    valid_over = BASE_SCHEMA + """\
derived asks(a: Item, g: Group): Bool = a.group = g
derived score(a: Item, g: Group): Int
  over asks(a, g)
  = a.qty
"""
    res_unknown, res_order, res_non_bool, res_open, res_valid = check_sources(
        unknown_over, wrong_arg_order, non_bool_domain, open_kind_domain, valid_over
    )

    r001 = [d for d in res_unknown["diagnostics"] if d["code"] == "R001"]
    assert len(r001) == 1 and r001[0]["span"] == at(unknown_over, "missing_domain", after="over "), res_unknown

    assert any(d["code"] == "R003" for d in res_order["diagnostics"]), res_order
    assert any(d["code"] == "R003" for d in res_non_bool["diagnostics"]), res_non_bool
    assert any(d["code"] == "R004" for d in res_open["diagnostics"]), res_open
    assert res_valid["diagnostics"] == [] and res_valid["format"] == "rezono.module/5", res_valid


def test_check_module_checks_derived_table():
    bad_projection_in_table = BASE_SCHEMA + """\
extend x: Item
  derived band: Text
    table first
      | entries.spec.nodes.sum() | -> band |
      | 10..                     | "high"  |
      | -                        | "low"   |
"""
    bad_cell_type = BASE_SCHEMA + """\
extend x: Item
  derived band: Text
    table first
      | entries.sum(spec.nodes) | -> band |
      | "wrong"                 | "high"  |
      | -                       | "low"   |
"""
    bad_output_type = BASE_SCHEMA + """\
extend x: Item
  derived band: Int
    table first
      | entries.sum(spec.nodes) | -> band |
      | 10..                    | "high"  |
      | -                       | 0       |
"""
    valid_table = BASE_SCHEMA + """\
extend x: Item
  derived band: Text
    table first
      | entries.sum(spec.nodes) | -> band |
      | 10..                    | "high"  |
      | -                       | "low"   |
"""
    res_proj, res_cell, res_out, res_valid = check_sources(
        bad_projection_in_table, bad_cell_type, bad_output_type, valid_table
    )

    r028 = [d for d in res_proj["diagnostics"] if d["code"] == "R028"]
    assert len(r028) == 1, res_proj
    assert r028[0]["span"] == at(bad_projection_in_table, "entries.spec.nodes", after="table first"), r028[0]
    assert "entries.sum(spec.nodes)" in (r028[0]["hint"] or ""), r028[0]

    assert any(d["code"] == "R003" for d in res_cell["diagnostics"]), res_cell
    assert any(d["code"] == "R003" for d in res_out["diagnostics"]), res_out
    assert res_valid["diagnostics"] == [] and res_valid["format"] == "rezono.module/5", res_valid


def test_check_module_checks_step_declarations():
    step_base = BASE_SCHEMA + """\
kind Target
  score: Int
  label: Text
kind Plan
  item: Item
  target: Target
  token: Text
derived ready(p: Plan): Bool = p.item.qty > 0
derived blocked(t: Target): Bool = t.score > 100
derived scope(g: Group): Bool = g.tag != ""
derived readback(g: Group): Bool = g.tag != ""
"""
    bad_when_proj = step_base + """\
step apply_plan(p: Plan)
  when p.item.entries.spec.nodes.sum() > 0
  forbid blocked(p.target) within scope(p.item.group)
  effect write_target
    + Target.score(p.target) = p.item.qty
  confirm readback(p.item.group) token p.token
"""
    bad_effect_proj = step_base + """\
step apply_plan(p: Plan)
  when ready(p)
  effect write_target
    + Target.score(p.target) = p.item.entries.spec.nodes.sum()
  confirm readback(p.item.group) token p.token
"""
    bad_effect_type = step_base + """\
step apply_plan(p: Plan)
  when ready(p)
  effect write_target
    + Target.score(p.target) = p.token
  confirm readback(p.item.group) token p.token
"""
    bad_confirm_proj = step_base + """\
step apply_plan(p: Plan)
  when ready(p)
  effect write_target
    + Target.score(p.target) = p.item.qty
  confirm readback(p.item.group) token p.item.entries.spec.nodes.sum()
"""
    valid_step = step_base + """\
step apply_plan(p: Plan)
  when ready(p) and p.item.entries.sum(spec.nodes) > 0
  forbid blocked(p.target) within scope(p.item.group)
  effect write_target
    + Target.score(p.target) = p.item.entries.sum(spec.nodes)
  confirm readback(p.item.group) token p.token
"""
    res_when, res_eff_proj, res_eff_ty, res_conf, res_valid = check_sources(
        bad_when_proj, bad_effect_proj, bad_effect_type, bad_confirm_proj, valid_step
    )

    assert any(d["code"] == "R028" for d in res_when["diagnostics"]), res_when
    assert any(d["code"] == "R028" for d in res_eff_proj["diagnostics"]), res_eff_proj
    assert any(d["code"] == "R003" for d in res_eff_ty["diagnostics"]), res_eff_ty
    assert any(d["code"] == "R028" for d in res_conf["diagnostics"]), res_conf
    assert res_valid["diagnostics"] == [] and res_valid["format"] == "rezono.module/5", res_valid


def test_check_module_checks_example_declarations():
    bad_expect_proj = BASE_SCHEMA + """\
example "collection projection in expect"
  given
    i1.qty = 5
  expect
    i1.entries.spec.nodes.sum() = 5
"""
    bad_given_proj = BASE_SCHEMA + """\
example "collection projection in given"
  given
    i1.qty = i1.entries.spec.nodes.sum()
  expect
    i1.qty = 5
"""
    bad_given_type = BASE_SCHEMA + """\
example "wrong type in given"
  given
    i1.qty = "not_an_int"
  expect
    i1.qty = 5
"""
    bad_expect_type = BASE_SCHEMA + """\
example "wrong type in expect"
  given
    i1.qty = 5
  expect
    i1.qty = "not_an_int"
"""
    valid_example = BASE_SCHEMA + """\
check positive_qty: Item.all(qty > 0)
example "explicit aggregate in expect"
  given
    i1.qty = 5
  expect
    i1.entries.sum(spec.nodes) = 0
    i1.qty = 5
"""
    res_exp_proj, res_giv_proj, res_giv_ty, res_exp_ty, res_valid = check_sources(
        bad_expect_proj, bad_given_proj, bad_given_type, bad_expect_type, valid_example
    )

    r028_exp = [d for d in res_exp_proj["diagnostics"] if d["code"] == "R028"]
    assert len(r028_exp) == 1, res_exp_proj
    assert r028_exp[0]["span"] == at(bad_expect_proj, "i1.entries.spec.nodes", after="expect"), r028_exp[0]
    assert "i1.entries.sum(spec.nodes)" in (r028_exp[0]["hint"] or ""), r028_exp[0]

    assert any(d["code"] == "R028" for d in res_giv_proj["diagnostics"]), res_giv_proj
    assert any(d["code"] == "R003" for d in res_giv_ty["diagnostics"]), res_giv_ty
    assert any(d["code"] == "R003" for d in res_exp_ty["diagnostics"]), res_exp_ty
    assert res_valid["diagnostics"] == [] and res_valid["format"] == "rezono.module/5", res_valid


def test_check_module_inherits_parent_slots_with_cycle_guard():
    transitive_and_forward = """\
rezono 1
pack sample
kind GrandChild is Child
  c: Int
  derived total: Int = a + b + c + bonus
kind Child is Base
  b: Int
kind Base
  a: Int
extend Base
  derived bonus: Int = a * 2
example "inherited slots work in examples too"
  given
    g1.a = 1
    g1.b = 2
    g1.c = 3
  expect
    g1.total = 8
"""
    child_override = """\
rezono 1
pack sample
kind Base
  value: Text
kind Child is Base
  value: Int
  derived doubled: Int = value * 2
"""
    cyclic_parents = """\
rezono 1
pack sample
kind LoopA is LoopB
  a: Int
kind LoopB is LoopA
  b: Int
  derived sum_ab: Int = a + b
"""
    res_trans, res_override, res_cycle = check_sources(
        transitive_and_forward, child_override, cyclic_parents
    )
    assert res_trans["diagnostics"] == [] and res_trans["format"] == "rezono.module/5", res_trans
    assert res_override["diagnostics"] == [] and res_override["format"] == "rezono.module/5", res_override
    assert res_cycle["diagnostics"] == [] and res_cycle["format"] == "rezono.module/5", res_cycle


def test_check_module_populates_currency_symbols_from_module_declarations():
    unit_eur = """\
rezono 1
pack sample
unit Euro = money EUR
kind Item
  price: Euro
  derived high: Bool = price > € 100
  derived band: Text
    table first
      | price    | -> band |
      | € 100..  | "high"  |
      | -        | "low"   |
"""
    money_generic = """\
rezono 1
pack sample
kind Item
  amount: Money<EUR>
  derived high: Bool = amount > € 38_520.50
"""
    undeclared_currency = """\
rezono 1
pack sample
unit Usd = money USD
kind Item
  price: Usd
  derived ok: Bool = price > $ 50
  derived bad: Bool = price > € 50
"""
    ambiguous_dollar = """\
rezono 1
pack sample
unit Usd = money USD
unit Cad = money CAD
kind Item
  price: Usd
  derived bad: Bool = price > $ 50
"""
    res_unit, res_money, res_undeclared, res_ambig = check_sources(
        unit_eur, money_generic, undeclared_currency, ambiguous_dollar
    )

    assert res_unit["diagnostics"] == [] and res_unit["format"] == "rezono.module/5", res_unit
    assert res_money["diagnostics"] == [] and res_money["format"] == "rezono.module/5", res_money

    r001_undec = [d for d in res_undeclared["diagnostics"] if d["code"] == "R001"]
    assert len(r001_undec) == 1 and r001_undec[0]["span"]["text"] == "€", res_undeclared

    r001_ambig = [d for d in res_ambig["diagnostics"] if d["code"] == "R001"]
    assert len(r001_ambig) == 1 and r001_ambig[0]["span"]["text"] == "$", res_ambig
