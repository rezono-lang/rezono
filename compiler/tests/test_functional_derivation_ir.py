"""Functional derivation IR (`rezono.rules/2`), closed-domain requirement, conflict policy, per-derivation
stratification, access-boundary refusal (`may_read` and `may_read_full`), rational column support, and
functional view profiling/weights (`VIEW_KINDS`, `views_by_kind`, `rules_sql.views`, `view_cost_mb`)
(decisions/language-rezono-1.md, sections 2, 4, 5.2, 5.3, 5.4 and 5.8)."""

from __future__ import annotations

from pathlib import Path

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest

from rezono_compiler import emit, rules as ir, rules_split, rules_sql

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"


class MissingFunctionalDerivationIR(AssertionError):
    """rezono.rules/2 functional derivation IR, stratification, access boundary, or profiling is incomplete."""


def _validator(schema_name: str) -> Validator:
    definition = yaml_loader.load(str(CONTRACTS / schema_name), target_class=SchemaDefinition)
    return Validator(definition, validation_plugins=[JsonschemaValidationPlugin(closed=True)])


def _validate(schema_name: str, instance: dict, target_class: str) -> list[str]:
    report = _validator(schema_name).validate(instance, target_class)
    return [item.message for item in report.results]


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *,
          stratum: str = "1", aggregates: list[dict] | None = None, module: str = "core") -> dict:
    doc = {
        "id": rid,
        "module": module,
        "stratum": stratum,
        "head": {"relation": head_rel, "terms": head_terms},
        "body": body,
        "origin": {"file": f"rules/{module}.rezono", "line": "1"},
    }
    if aggregates:
        doc["aggregates"] = aggregates
    return doc


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _interleaved_program() -> dict:
    """Bool recursion (`reach`) -> functional A (`pick_a`) -> Bool B (`flagged_b`) -> functional C (`score_c`),
    plus a deterministic projection functional derivation (`proj_tag`) and a rational functional derivation (`ratio_val`)."""
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "item__tag", "role": "base", "key": [_col("id"), _col("tag")]},
            {"name": "edge", "role": "base", "key": [_col("a"), _col("b")]},
            {"name": "cand_a", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand_b", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand_c", "role": "base", "key": [_col("a"), _col("b"), _col("n", "integer")]},
            {"name": "rate_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {"name": "reach", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("a"), _col("b")]},
            {
                "name": "proj_tag", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "string"), "conflict_policy": "publish",
            },
            {
                "name": "pick_a", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("a"), _col("b")], "domain": "reach",
                "value": _col("value", "string"), "conflict_policy": "publish",
            },
            {"name": "flagged_b", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("a"), _col("b")]},
            {
                "name": "score_c", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("a"), _col("b")], "domain": "flagged_b",
                "value": _col("value", "integer"), "conflict_policy": "block",
            },
            {
                "name": "ratio_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("reach_base", "reach", ["?a", "?b"], [_lit("edge", "?a", "?b")], stratum="1"),
            _rule("reach_step", "reach", ["?a", "?c"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("edge", "?b", "?c")], stratum="1"),
            _rule("proj_tag_rule", "proj_tag", ["?id", "?t"],
                  [_lit("item", "?id"), _lit("item__tag", "?id", "?t")], stratum="1"),
            _rule("pick_a_first", "pick_a", ["?a", "?b", "?v"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("cand_a", "?a", "?b", "?v")], stratum="2"),
            _rule("pick_a_second", "pick_a", ["?a", "?b", "?v"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("cand_b", "?a", "?b", "?v")], stratum="2"),
            _rule("flagged_b_known", "flagged_b", ["?a", "?b"],
                  [_lit("pick_a", "?a", "?b", "known", "", "?v", stratum="2")], stratum="2"),
            _rule("flagged_b_conflict", "flagged_b", ["?a", "?b"],
                  [_lit("pick_a", "?a", "?b", "invalid", "?r", "?v", stratum="2")], stratum="2"),
            _rule("score_c_rule", "score_c", ["?a", "?b", "?n"],
                  [_lit("flagged_b", "?a", "?b", stratum="2"), _lit("cand_c", "?a", "?b", "?n")], stratum="3"),
            _rule("ratio_val_rule", "ratio_val", ["?id", "?r"],
                  [_lit("item", "?id"), _lit("rate_in", "?id", "?r")], stratum="1"),
        ],
    }


def _expect_ir_error(doc: dict, label: str, problems: list[str], *, code: str | None = None) -> None:
    try:
        ir.load(doc, require_witness=False)
    except ir.IRError as exc:
        if code is not None and exc.code != code:
            problems.append(f"{label}: expected IRError({code!r}), got IRError({exc.code!r}: {exc})")
    else:
        problems.append(f"{label}: expected IRError({code or 'any'}), but ir.load succeeded")


def test_functional_derivation_ir_and_stratification():
    # Counter-case: rezono.rules/1 plain derived relations keep their existing IR loading and `relation` view kind.
    v1_doc = {
        "format": "rezono.rules/1",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "listed", "role": "derived", "module": "core", "explain": "on_demand", "key": [_col("id")]},
        ],
        "rules": [_rule("listed_r", "listed", ["?x"], [_lit("item", "?x")], stratum="1")],
    }
    v1_prog = ir.load(v1_doc, require_witness=False)
    assert rules_split.views_by_kind(v1_prog, "listed") == {"relation": 1, "witness": 0, "outcome": 0}
    assert rules_sql.views(v1_prog, "listed") == 1

    problems: list[str] = []

    # 1. Core reason codes (`no_value`, `multiple_values`) documented in contracts/value.yaml and docs/publication/l0.md.
    value_yaml = (CONTRACTS / "value.yaml").read_text(encoding="utf-8")
    l0_doc = (ROOT / "docs" / "publication" / "l0.md").read_text(encoding="utf-8")
    for code in ("no_value", "multiple_values"):
        if code not in value_yaml:
            problems.append(f"contracts/value.yaml does not list new core reason code {code!r}")
        if code not in l0_doc:
            problems.append(f"docs/publication/l0.md does not list new core reason code {code!r}")
    assert _validate("value.yaml", {"state": "unknown", "reason": "no_value"}, "Value") == []
    assert _validate("value.yaml", {"state": "invalid", "reason": "multiple_values"}, "Value") == []

    # 2. contracts/rules.yaml admits rezono.rules/2 + role: functional; contracts/bundle.yaml admits rational + functional.
    prog_doc = _interleaved_program()
    rules_errs = _validate("rules.yaml", prog_doc, "RuleProgram")
    if rules_errs:
        problems.append(f"contracts/rules.yaml rejected valid rezono.rules/2 functional program: {rules_errs[:3]}")
    bundle_yaml = (CONTRACTS / "bundle.yaml").read_text(encoding="utf-8")
    if "rational" not in bundle_yaml:
        problems.append("contracts/bundle.yaml RuleColumnType does not admit `rational`")

    # 3. `rational` column type in rules.py, rules_sql.py, rules_split.py and `functional` in emit.VIEW_KINDS.
    if "rational" not in ir.TYPES:
        problems.append(f"rules.TYPES missing 'rational': {ir.TYPES!r}")
    if "rational" not in rules_sql.SQL_TYPE:
        problems.append(f"rules_sql.SQL_TYPE missing 'rational': {rules_sql.SQL_TYPE!r}")
    if "functional" not in emit.VIEW_KINDS:
        problems.append(f"emit.VIEW_KINDS missing 'functional': {emit.VIEW_KINDS!r}")
    else:
        costs = {k: 10 for k in emit.VIEW_KINDS}
        mem = emit.view_budget({"profile": "p", "engine": {"build_memory_mb": 1000, "view_cost_mb": costs}})
        if mem.cost("functional") != 10:
            problems.append(f"emit.view_budget did not preserve view_cost_mb['functional']: {mem}")
        missing_func = {k: 10 for k in emit.VIEW_KINDS if k != "functional"}
        try:
            emit.view_budget({"profile": "p", "engine": {"build_memory_mb": 1000, "view_cost_mb": missing_func}})
        except Exception:
            pass
        else:
            problems.append("emit.view_budget accepted a build_memory_mb profile missing view_cost_mb['functional']")

    # 4. Load the interleaved rezono.rules/2 program and check per-derivation stratification + profiling weights.
    try:
        prog = ir.load(prog_doc, require_witness=False)
    except ir.IRError as exc:
        problems.append(f"ir.load rejected valid interleaved rezono.rules/2 program: {exc}")
    else:
        if not (prog.strata["reach"] < prog.strata["pick_a"] <= prog.strata["flagged_b"] < prog.strata["score_c"]):
            problems.append(f"unexpected interleaved strata: {prog.strata!r}")

        # views_by_kind counts "functional" instead of "relation" (no double-counting).
        proj_kinds = rules_split.views_by_kind(prog, "proj_tag")
        if proj_kinds.get("functional") != 1 or proj_kinds.get("relation", 0) != 0:
            problems.append(f"proj_tag views_by_kind must count functional=1 without relation: {proj_kinds!r}")
        score_kinds = rules_split.views_by_kind(prog, "score_c")
        if score_kinds.get("functional") != 1 or score_kinds.get("relation", 0) != 0 or score_kinds.get("outcome", 0) != 1:
            problems.append(f"score_c (conflict_policy=block) views_by_kind mismatch: {score_kinds!r}")

        # Weight 1 for deterministic projection, weight 2 for candidate-aggregating / precedence / rational.
        if rules_sql.views(prog, "proj_tag") != 1:
            problems.append(f"deterministic projection proj_tag expected weight 1, got {rules_sql.views(prog, 'proj_tag')}")
        if rules_sql.views(prog, "pick_a") != 2:
            problems.append(f"candidate-aggregating pick_a expected weight 2, got {rules_sql.views(prog, 'pick_a')}")
        if rules_sql.views(prog, "ratio_val") != 2:
            problems.append(f"rational functional ratio_val expected weight 2, got {rules_sql.views(prog, 'ratio_val')}")

        # rules_split.decode / export_select supports rational columns.
        try:
            decoded = rules_split.decode(prog, "rate_in", ["i1", "3/4"])
            if decoded != ("i1", "3/4"):
                problems.append(f"rules_split.decode mismatch for rational column: {decoded!r}")
        except Exception as exc:
            problems.append(f"rules_split.decode failed on rational column: {exc}")

        # 5. Missing domain, mismatched/Cartesian domain, invalid conflict_policy, and open-domain negation/aggregation.
        no_domain = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "item", "role": "base", "key": [_col("id")]},
                {"name": "bad_fn", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("id")], "value": _col("value"), "conflict_policy": "publish"},
            ],
            "rules": [_rule("r1", "bad_fn", ["?x", "ok"], [_lit("item", "?x")], stratum="1")],
        }
        _expect_ir_error(no_domain, "functional without domain", problems)

        cartesian_domain = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "item", "role": "base", "key": [_col("id")]},
                {"name": "group", "role": "base", "key": [_col("id")]},
                {"name": "pair_fn", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("a"), _col("b")], "domain": "item",
                 "value": _col("value"), "conflict_policy": "publish"},
            ],
            "rules": [_rule("r1", "pair_fn", ["?a", "?b", "ok"],
                            [_lit("item", "?a"), _lit("group", "?b")], stratum="1")],
        }
        _expect_ir_error(cartesian_domain, "2-key functional with mismatched 1-key domain (Cartesian product)", problems)

        bad_policy = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "item", "role": "base", "key": [_col("id")]},
                {"name": "bad_pol", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("id")], "domain": "item",
                 "value": _col("value"), "conflict_policy": "silent"},
            ],
            "rules": [_rule("r1", "bad_pol", ["?x", "ok"], [_lit("item", "?x")], stratum="1")],
        }
        _expect_ir_error(bad_policy, "invalid conflict_policy", problems)

        # 6. Refused cycles through functional derivations.
        cycle_doc = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "item", "role": "base", "key": [_col("id")]},
                {"name": "loop_dom", "role": "derived", "module": "core", "explain": "on_demand", "key": [_col("id")]},
                {"name": "loop_fn", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("id")], "domain": "loop_dom", "value": _col("value"), "conflict_policy": "publish"},
            ],
            "rules": [
                _rule("dom_base", "loop_dom", ["?x"], [_lit("item", "?x")], stratum="1"),
                _rule("dom_from_fn", "loop_dom", ["?x"],
                      [_lit("loop_fn", "?x", "known", "", "?v", stratum="2")], stratum="1"),
                _rule("fn_r", "loop_fn", ["?x", "v1"], [_lit("loop_dom", "?x", stratum="1")], stratum="2"),
            ],
        }
        _expect_ir_error(cycle_doc, "cycle through functional derivation", problems, code="not_stratified")

        # 7. Access boundary: neither `may_read` nor `may_read_full` may depend on a `functional` derivation or `calc`.
        for access_rel, head_terms in (
            ("may_read", ["?r", "item", "?x"]),
            ("may_read_full", ["?r", "item"]),
        ):
            cols = ([_col("role"), _col("kind"), _col("id")] if access_rel == "may_read"
                    else [_col("role"), _col("kind")])
            access_fn_doc = {
                "format": "rezono.rules/2", "pack": "sample",
                "relations": [
                    {"name": "role", "role": "base", "key": [_col("id")]},
                    {"name": "item", "role": "base", "key": [_col("id")]},
                    {"name": "item__tag", "role": "base", "key": [_col("id"), _col("tag")]},
                    {"name": "item_tag", "role": "functional", "module": "core", "explain": "on_demand",
                     "key": [_col("id")], "domain": "item", "value": _col("value"), "conflict_policy": "publish"},
                    {"name": access_rel, "role": "derived", "module": "core", "explain": "on_demand", "key": cols},
                ],
                "rules": [
                    _rule("tag_r", "item_tag", ["?x", "?t"], [_lit("item", "?x"), _lit("item__tag", "?x", "?t")], stratum="1"),
                    _rule("acc_r", access_rel, head_terms,
                          [_lit("role", "?r"), _lit("item_tag", "?x", "known", "", "public", stratum="1")], stratum="2"),
                ],
            }
            _expect_ir_error(access_fn_doc, f"{access_rel} depending on functional derivation", problems)

        # `may_read_full` depending on a `role: calc` selection must also be refused.
        access_calc_doc = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "role", "role": "base", "key": [_col("id")]},
                {"name": "calc__flag", "role": "calc", "world": "open",
                 "key": [_col("subject"), _col("value", "integer"), _col("state"), _col("reason")]},
                {"name": "may_read_full", "role": "derived", "module": "core", "explain": "on_demand",
                 "key": [_col("role"), _col("kind")]},
            ],
            "rules": [
                _rule("acc_calc", "may_read_full", ["?r", "item"],
                      [_lit("role", "?r"), _lit("calc__flag", "?s", "1", "known", "", stratum="0")], stratum="1"),
            ],
        }
        _expect_ir_error(access_calc_doc, "may_read_full depending on calc selection", problems)

    if problems:
        raise MissingFunctionalDerivationIR("\n".join(problems))


def _bound_program(fmt: str, value_type: str, rule_doc: dict) -> dict:
    return {
        "format": fmt,
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "item__num", "role": "base", "key": [_col("id"), _col("v", value_type)]},
            {"name": "out", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("id"), _col("v", value_type)]},
        ],
        "rules": [rule_doc],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M3: decisions/language-rezono-1-refinements.md: section 3.4C.3; compiler/rezono_compiler/rules.py "
        "must enforce symmetric BOUND = 2^63 - 1 at rezono.rules/2 IR load, refusing -2^63 "
        "(-9223372036854775808) in integer and rational constant positions while accepting -(2^63 - 1) "
        "and keeping rezono.rules/1 backwards-compatible."
    ),
)
def test_rules_v2_refuses_min_int64_constant_and_accepts_symmetric_bound():
    min_i64 = "-9223372036854775808"
    max_i64_plus_1 = "9223372036854775808"
    min_bound = "-9223372036854775807"
    max_bound = "9223372036854775807"

    # Counter-case: legacy rezono.rules/1 keeps [-2^63, 2^63 - 1].
    v1_min = _bound_program(
        "rezono.rules/1", "integer",
        _rule("r1", "out", ["?x", min_i64], [_lit("item", "?x")], stratum="1"),
    )
    ir.load(v1_min, require_witness=False)

    # Accepted in rezono.rules/2: symmetric +/- (2^63 - 1) across integer and rational positions.
    for val in (min_bound, max_bound):
        ir.load(_bound_program(
            "rezono.rules/2", "integer",
            _rule("r_head", "out", ["?x", val], [_lit("item", "?x")], stratum="1"),
        ), require_witness=False)
        ir.load(_bound_program(
            "rezono.rules/2", "integer",
            _rule("r_body", "out", ["?x", val], [_lit("item__num", "?x", val)], stratum="1"),
        ), require_witness=False)
        cond_rule = _rule("r_cond", "out", ["?x", "?v"], [_lit("item__num", "?x", "?v")], stratum="1")
        cond_rule["conditions"] = [{"op": "ge", "left": "?v", "right": val}]
        ir.load(_bound_program("rezono.rules/2", "integer", cond_rule), require_witness=False)
        assign_rule = _rule("r_assign", "out", ["?x", "?y"], [_lit("item__num", "?x", "?v")], stratum="1")
        assign_rule["assignments"] = [{"var": "?y", "op": "add", "left": "?v", "right": val}]
        ir.load(_bound_program("rezono.rules/2", "integer", assign_rule), require_witness=False)

    for rat in (min_bound, max_bound, f"{min_bound}/2", f"{max_bound}/2"):
        ir.load(_bound_program(
            "rezono.rules/2", "rational",
            _rule("r_rat", "out", ["?x", rat], [_lit("item", "?x")], stratum="1"),
        ), require_witness=False)

    # Refused in rezono.rules/2: -2^63 and +2^63 in integer and rational constant positions.
    problems: list[str] = []
    for bad in (min_i64, max_i64_plus_1):
        _expect_ir_error(
            _bound_program("rezono.rules/2", "integer",
                           _rule("bad_head", "out", ["?x", bad], [_lit("item", "?x")], stratum="1")),
            f"rezono.rules/2 integer head constant {bad}", problems,
        )
        _expect_ir_error(
            _bound_program("rezono.rules/2", "integer",
                           _rule("bad_body", "out", ["?x", "0"], [_lit("item__num", "?x", bad)], stratum="1")),
            f"rezono.rules/2 integer body constant {bad}", problems,
        )
        bad_cond = _rule("bad_cond", "out", ["?x", "?v"], [_lit("item__num", "?x", "?v")], stratum="1")
        bad_cond["conditions"] = [{"op": "ge", "left": "?v", "right": bad}]
        _expect_ir_error(
            _bound_program("rezono.rules/2", "integer", bad_cond),
            f"rezono.rules/2 integer condition constant {bad}", problems,
        )
        bad_assign = _rule("bad_assign", "out", ["?x", "?y"], [_lit("item__num", "?x", "?v")], stratum="1")
        bad_assign["assignments"] = [{"var": "?y", "op": "add", "left": "?v", "right": bad}]
        _expect_ir_error(
            _bound_program("rezono.rules/2", "integer", bad_assign),
            f"rezono.rules/2 integer assignment constant {bad}", problems,
        )

    for bad_rat in (min_i64, f"{min_i64}/3"):
        _expect_ir_error(
            _bound_program("rezono.rules/2", "rational",
                           _rule("bad_rat", "out", ["?x", bad_rat], [_lit("item", "?x")], stratum="1")),
            f"rezono.rules/2 rational head constant {bad_rat}", problems,
        )
        bad_rat_cond = _rule("bad_rat_cond", "out", ["?x", "?v"], [_lit("item__num", "?x", "?v")], stratum="1")
        bad_rat_cond["conditions"] = [{"op": "eq", "left": "?v", "right": bad_rat}]
        _expect_ir_error(
            _bound_program("rezono.rules/2", "rational", bad_rat_cond),
            f"rezono.rules/2 rational condition constant {bad_rat}", problems,
        )

    assert not problems, "\n".join(problems)
