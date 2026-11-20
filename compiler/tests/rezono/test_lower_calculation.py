"""A calculation written in Rezono lowers to the program its calc/*.yaml file states: the same ir/calc.json and
calculation SQL (decisions/language-calculations.md). The existing files of examples/subsidy and of the
scheme it imports are the oracle; the module forms below are written by hand from that decision."""

import pytest

from calc_packs import (SCHEME, SUBSIDY, MissingCalculationLowering, calc_ir, definition, derived, examples, form,
                        lit, lowered, path, row_parameter)
from rezono_compiler import pack


def drift_and_date() -> list:
    """calc/drift.yaml and calc/date.yaml of examples/subsidy."""
    payment_difference = derived(
        "payment_difference",
        definition("paid_minus_award", path("paid"), {"arith": ["-", path("ledger_paid", "cents"), path("award")]}),
    )
    return [{"asOf": "2026-11-10", "known": "2026-11-10"},
            {"extend": "Application", "derived": [payment_difference]}]


def test_lower_calculation(tmp_path):
    expected = calc_ir(examples(tmp_path / "legacy") / SUBSIDY)
    assert expected["ir/calc.json"]["rules"]

    candidate = examples(tmp_path / "candidate") / SUBSIDY
    for name in ("drift.yaml", "date.yaml"):
        (candidate / "calc" / name).unlink()
    form(candidate, drift_and_date())
    assert lowered(candidate) == expected

    # Counter-case: all derived values of one module share one subject.
    twice = examples(tmp_path / "twice") / SUBSIDY
    for name in ("drift.yaml", "date.yaml"):
        (twice / "calc" / name).unlink()
    other = derived("persons_twice", definition("double", lit("true"), {"arith": ["*", path("persons"), lit("2")]}))
    form(twice, drift_and_date() + [{"extend": "Household", "derived": [other]}])
    with pytest.raises(pack.CompileError, match="two subjects"):
        calc_ir(twice)


def award() -> list:
    """calc/award.yaml of the scheme that examples/subsidy imports. Inside entitlement the derived value advice_allowance is
    written Application.advice_allowance, because a parameter has the same name (the section Leaves)."""
    rule_leaf = {"dot": [{"kind": "Application"}, "advice_allowance"]}
    income, costs = path("assessed_income", "cents"), path("assessed_costs", "cents")
    rate = lambda name: {"call": ["round", [{"arith": ["/", {"arith": ["*", costs, path(name)]}, lit("1000000")]}]]}
    values = [
        derived("income_threshold", definition("base_plus_persons", lit("true"), {"arith": [
            "+", path("income_threshold_base"),
            {"arith": ["*", path("household_size", "persons"), path("income_threshold_per_person")]}]})),
        derived("income_limit", definition("threshold_plus_margin", lit("true"),
                                           {"arith": ["+", path("income_threshold"), path("income_margin")]})),
        derived("cost_share",
                definition("full_rate", {"cmp": ["<=", income, path("income_threshold")]}, rate("full_rate")),
                definition("partial_rate", {"and": [{"cmp": ["<", path("income_threshold"), income]},
                                                    {"cmp": ["<=", income, path("income_limit")]}]},
                           rate("partial_rate")),
                definition("above_the_limit", {"cmp": ["<", path("income_limit"), income]}, lit("0"))),
        derived("advice_allowance", definition("allowance_or_nothing", lit("true"), {"when": [
            {"and": [path("advised"), {"cmp": ["<", lit("0"), path("cost_share")]}]},
            path("advice_allowance"), lit("0")]})),
        derived("entitlement", definition("share_plus_allowance", lit("true"),
                                          {"arith": ["+", path("cost_share"), rule_leaf]})),
        derived("award", definition("at_most_the_maximum", lit("true"),
                                    {"call": ["min", [path("entitlement"), path("maximum_award")]]})),
    ]
    parameters = ["income_threshold_base", "income_threshold_per_person", "income_margin", "full_rate",
                  "partial_rate", "advice_allowance", "maximum_award"]
    return [*map(row_parameter, parameters), {"extend": "Application", "derived": values}]


def test_lower_calculation_award(tmp_path):
    expected = calc_ir(examples(tmp_path / "legacy") / SCHEME)
    assert len(expected["ir/calc.json"]["rules"]) == 6

    candidate = examples(tmp_path / "candidate") / SCHEME
    (candidate / "calc" / "award.yaml").unlink()
    form(candidate, award())
    assert lowered(candidate) == expected

    # Counter-case: written bare, advice_allowance inside entitlement names both the parameter and the value.
    bare = examples(tmp_path / "bare") / SCHEME
    (bare / "calc" / "award.yaml").unlink()
    decls = award()
    entitlement = decls[-1]["derived"][4]["versions"][0]["definitions"][0]
    entitlement["value"]["arith"][2] = path("advice_allowance")
    form(bare, decls)
    with pytest.raises(pack.CompileError, match="ambiguous leaf"):
        calc_ir(bare)
