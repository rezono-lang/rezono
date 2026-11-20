"""Functional derivation IR (`rezono.rules/2`), mandatory closed-domain requirement (`functional_open_domain`),
core reason codes (`no_match`, `multiple_values`), conflict policy, per-derivation stratification, access-boundary
refusal (`may_read` and `may_read_full`), rational column support, `<k>_<d>` derived-property metadata, and
functional view kinds/weights (`emit.VIEW_KINDS` with `functional` and `functional_aggregate`, preserving
`sum(views_by_kind) == rules_sql.views`, and `rules_split.view_weight`)
(decisions/language-rezono-1.md, sections 2, 4, 5.2, 5.3, 5.4, 5.8 and 8)."""

from __future__ import annotations

from pathlib import Path

from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin
from linkml_runtime.linkml_model.meta import SchemaDefinition
from linkml_runtime.loaders import yaml_loader
import pytest

from rezono_compiler import emit, rules as ir, rules_split, rules_sql
from rezono_publication import l0 as publication_l0

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
    plus a deterministic single-key derived property projection (`item_tag` for `Item.tag`) and a rational
    functional derivation (`item_ratio`)."""
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "item__tag", "role": "base", "key": [_col("id"), _col("tag")]},
            {"name": "edge", "role": "base", "key": [_col("a"), _col("b")]},
            {"name": "cand_a", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand_b", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "cand_c1", "role": "base", "key": [_col("a"), _col("b"), _col("n", "integer")]},
            {"name": "cand_c2", "role": "base", "key": [_col("a"), _col("b"), _col("n", "integer")]},
            {"name": "rate_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {"name": "reach", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("a"), _col("b")]},
            {
                "name": "item_tag", "role": "functional", "module": "core", "explain": "on_demand",
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
                "name": "item_ratio", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("reach_base", "reach", ["?a", "?b"], [_lit("edge", "?a", "?b")], stratum="1"),
            _rule("reach_step", "reach", ["?a", "?c"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("edge", "?b", "?c")], stratum="1"),
            _rule("item_tag_rule", "item_tag", ["?id", "?t"],
                  [_lit("item", "?id"), _lit("item__tag", "?id", "?t")], stratum="1"),
            _rule("pick_a_first", "pick_a", ["?a", "?b", "?v"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("cand_a", "?a", "?b", "?v")], stratum="2"),
            _rule("pick_a_second", "pick_a", ["?a", "?b", "?v"],
                  [_lit("reach", "?a", "?b", stratum="1"), _lit("cand_b", "?a", "?b", "?v")], stratum="2"),
            _rule("flagged_b_known", "flagged_b", ["?a", "?b"],
                  [_lit("pick_a", "?a", "?b", "known", "", "?v", stratum="2")], stratum="2"),
            _rule("flagged_b_conflict", "flagged_b", ["?a", "?b"],
                  [_lit("pick_a", "?a", "?b", "invalid", "?r", "?v", stratum="2")], stratum="2"),
            _rule("score_c_first", "score_c", ["?a", "?b", "?n"],
                  [_lit("flagged_b", "?a", "?b", stratum="2"), _lit("cand_c1", "?a", "?b", "?n")], stratum="3"),
            _rule("score_c_second", "score_c", ["?a", "?b", "?n"],
                  [_lit("flagged_b", "?a", "?b", stratum="2"), _lit("cand_c2", "?a", "?b", "?n")], stratum="3"),
            _rule("item_ratio_rule", "item_ratio", ["?id", "?r"],
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


@pytest.mark.xfail(
    strict=True,
    raises=MissingFunctionalDerivationIR,
    reason="M3: decisions/language-rezono-1.md: Implement rezono.rules/2 `role: functional` with mandatory closed "
           "`domain` (refusing open domains with `functional_open_domain`), `<k>_<d>` derived-property naming and "
           "`kind`/`property` bundle metadata, co-located `(key..., state, reason, value)` payload, `rational` column "
           "type in rules.py/rules_sql.py/rules_split.py/contracts/bundle.yaml, new core reason codes `no_match` "
           "(not_applicable/unknown) and `multiple_values` (invalid) in contracts/value.yaml, docs/publication/l0.md, "
           "and publication/rezono_publication/l0.py (`CORE_REASONS`), `conflict_policy` (publish vs block), "
           "per-derivation stratification across derived and functional relations, refusal of `may_read` AND "
           "`may_read_full` depending on functional or calc relations, and `functional` / `functional_aggregate` view "
           "kinds in emit.VIEW_KINDS with `rules_split.view_weight` (1 vs 2) preserving "
           "`sum(views_by_kind) == rules_sql.views`. Read sections 2, 4, 5.2, 5.3, 5.4, 5.8 and 8.",
)
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

    # 1. Core reason codes (`no_match`, `multiple_values`) in contracts/value.yaml, docs/publication/l0.md, and
    #    publication/rezono_publication/l0.py (`CORE_REASONS`).
    value_yaml = (CONTRACTS / "value.yaml").read_text(encoding="utf-8")
    l0_doc = (ROOT / "docs" / "publication" / "l0.md").read_text(encoding="utf-8")
    for code in ("no_match", "multiple_values"):
        if code not in value_yaml:
            problems.append(f"contracts/value.yaml does not list new core reason code {code!r}")
        if code not in l0_doc:
            problems.append(f"docs/publication/l0.md does not list new core reason code {code!r}")
    if set(publication_l0.CORE_REASONS.get("no_match", ())) != {"not_applicable", "unknown"}:
        problems.append(
            f"publication l0.CORE_REASONS['no_match'] expected {{'not_applicable', 'unknown'}}, "
            f"got {publication_l0.CORE_REASONS.get('no_match')!r}"
        )
    if set(publication_l0.CORE_REASONS.get("multiple_values", ())) != {"invalid"}:
        problems.append(
            f"publication l0.CORE_REASONS['multiple_values'] expected {{'invalid'}}, "
            f"got {publication_l0.CORE_REASONS.get('multiple_values')!r}"
        )
    assert _validate("value.yaml", {"state": "unknown", "reason": "no_match"}, "Value") == []
    assert _validate("value.yaml", {"state": "not_applicable", "reason": "no_match"}, "Value") == []
    assert _validate("value.yaml", {"state": "invalid", "reason": "multiple_values"}, "Value") == []

    # 2. contracts/rules.yaml admits rezono.rules/2 + role: functional; contracts/bundle.yaml admits rational +
    #    derived-property kind/property metadata.
    prog_doc = _interleaved_program()
    rules_errs = _validate("rules.yaml", prog_doc, "RuleProgram")
    if rules_errs:
        problems.append(f"contracts/rules.yaml rejected valid rezono.rules/2 functional program: {rules_errs[:3]}")
    bundle_yaml = (CONTRACTS / "bundle.yaml").read_text(encoding="utf-8")
    if "rational" not in bundle_yaml:
        problems.append("contracts/bundle.yaml RuleColumnType does not admit `rational`")

    # 3. `rational` column type in rules.py/rules_sql.py and both `functional` and `functional_aggregate` in VIEW_KINDS.
    if "rational" not in ir.TYPES:
        problems.append(f"rules.TYPES missing 'rational': {ir.TYPES!r}")
    if "rational" not in rules_sql.SQL_TYPE:
        problems.append(f"rules_sql.SQL_TYPE missing 'rational': {rules_sql.SQL_TYPE!r}")
    for kind in ("functional", "functional_aggregate"):
        if kind not in emit.VIEW_KINDS:
            problems.append(f"emit.VIEW_KINDS missing {kind!r}: {emit.VIEW_KINDS!r}")
    if {"functional", "functional_aggregate"} <= set(emit.VIEW_KINDS):
        costs = {k: 10 for k in emit.VIEW_KINDS}
        mem = emit.view_budget({"profile": "p", "engine": {"build_memory_mb": 1000, "view_cost_mb": costs}})
        if mem.cost("functional") != 10 or mem.cost("functional_aggregate") != 10:
            problems.append(f"emit.view_budget did not preserve functional view_cost_mb entries: {mem}")
        for missing_key in ("functional", "functional_aggregate"):
            incomplete = {k: 10 for k in emit.VIEW_KINDS if k != missing_key}
            try:
                emit.view_budget({"profile": "p", "engine": {"build_memory_mb": 1000, "view_cost_mb": incomplete}})
            except Exception:
                pass
            else:
                problems.append(f"emit.view_budget accepted a build_memory_mb profile missing {missing_key!r}")

    # 4. Load the interleaved rezono.rules/2 program and check per-derivation stratification + view kinds/weights.
    try:
        prog = ir.load(prog_doc, require_witness=False)
    except ir.IRError as exc:
        problems.append(f"ir.load rejected valid interleaved rezono.rules/2 program: {exc}")
    else:
        if not (prog.strata["reach"] < prog.strata["pick_a"] <= prog.strata["flagged_b"] < prog.strata["score_c"]):
            problems.append(f"unexpected interleaved strata: {prog.strata!r}")
        for fn_name in ("item_tag", "pick_a", "score_c", "item_ratio"):
            if prog.relations[fn_name].world != "closed":
                problems.append(f"functional relation {fn_name} must have world='closed', got {prog.relations[fn_name].world!r}")

        # views_by_kind counts "functional" (deterministic projection) or "functional_aggregate" (candidate-aggregating
        # / precedence / rational) instead of "relation", and sum(views_by_kind) == rules_sql.views is preserved!
        tag_kinds = rules_split.views_by_kind(prog, "item_tag")
        if tag_kinds.get("functional") != 1 or tag_kinds.get("relation", 0) != 0 or tag_kinds.get("functional_aggregate", 0) != 0:
            problems.append(f"item_tag views_by_kind expected functional=1 only: {tag_kinds!r}")
        pick_kinds = rules_split.views_by_kind(prog, "pick_a")
        if pick_kinds.get("functional_aggregate") != 1 or pick_kinds.get("relation", 0) != 0 or pick_kinds.get("functional", 0) != 0:
            problems.append(f"pick_a views_by_kind expected functional_aggregate=1 only: {pick_kinds!r}")
        ratio_kinds = rules_split.views_by_kind(prog, "item_ratio")
        if ratio_kinds.get("functional_aggregate") != 1 or ratio_kinds.get("relation", 0) != 0:
            problems.append(f"item_ratio views_by_kind expected functional_aggregate=1 only: {ratio_kinds!r}")
        score_kinds = rules_split.views_by_kind(prog, "score_c")
        if score_kinds.get("functional_aggregate") != 1 or score_kinds.get("relation", 0) != 0 or score_kinds.get("outcome", 0) != 1:
            problems.append(f"score_c (conflict_policy=block) views_by_kind mismatch: {score_kinds!r}")

        for rel_name in ("reach", "item_tag", "pick_a", "flagged_b", "score_c", "item_ratio"):
            raw_sum = sum(rules_split.views_by_kind(prog, rel_name).values())
            sql_views = rules_sql.views(prog, rel_name)
            if raw_sum != sql_views:
                problems.append(f"{rel_name}: sum(views_by_kind)={raw_sum} != rules_sql.views={sql_views}")

        # rules_split.view_weight applies weight 1 for functional and weight 2 for functional_aggregate.
        view_weight = getattr(rules_split, "view_weight", None)
        if view_weight is None:
            problems.append("rules_split.view_weight is missing")
        else:
            if view_weight(v1_prog, "listed") != rules_sql.views(v1_prog, "listed"):
                problems.append("rules_split.view_weight differs from rules_sql.views on legacy derived relation")
            if view_weight(prog, "item_tag") != 1:
                problems.append(f"deterministic projection item_tag expected view_weight 1, got {view_weight(prog, 'item_tag')}")
            if view_weight(prog, "pick_a") != 2:
                problems.append(f"candidate-aggregating pick_a expected view_weight 2, got {view_weight(prog, 'pick_a')}")
            if view_weight(prog, "item_ratio") != 2:
                problems.append(f"rational item_ratio expected view_weight 2, got {view_weight(prog, 'item_ratio')}")
            if view_weight(prog, "score_c") != 3:
                problems.append(f"block functional_aggregate score_c expected view_weight 3 (2+1), got {view_weight(prog, 'score_c')}")

        # rules_split.decode supports rational columns.
        try:
            decoded = rules_split.decode(prog, "rate_in", ["i1", "3/4"])
            if decoded != ("i1", "3/4"):
                problems.append(f"rules_split.decode mismatch for rational column: {decoded!r}")
        except Exception as exc:
            problems.append(f"rules_split.decode failed on rational column: {exc}")

        # 5. Missing domain, mismatched/Cartesian domain, open domain (`functional_open_domain`), and bad conflict_policy.
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

        open_base_domain = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "open_item", "role": "base", "world": "open", "key": [_col("id")]},
                {"name": "open_fn", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("id")], "domain": "open_item",
                 "value": _col("value"), "conflict_policy": "publish"},
            ],
            "rules": [_rule("r1", "open_fn", ["?x", "ok"], [_lit("open_item", "?x")], stratum="1")],
        }
        _expect_ir_error(open_base_domain, "functional over open base domain", problems, code="functional_open_domain")

        open_derived_domain = {
            "format": "rezono.rules/2", "pack": "sample",
            "relations": [
                {"name": "open_item", "role": "base", "world": "open", "key": [_col("id")]},
                {"name": "open_dom", "role": "derived", "module": "core", "explain": "on_demand",
                 "world": "open", "key": [_col("id")]},
                {"name": "open_fn", "role": "functional", "module": "core", "explain": "on_demand",
                 "key": [_col("id")], "domain": "open_dom",
                 "value": _col("value"), "conflict_policy": "publish"},
            ],
            "rules": [
                _rule("dom_r", "open_dom", ["?x"], [_lit("open_item", "?x")], stratum="1"),
                _rule("fn_r", "open_fn", ["?x", "ok"], [_lit("open_dom", "?x", stratum="1")], stratum="2"),
            ],
        }
        _expect_ir_error(open_derived_domain, "functional over open derived domain", problems, code="functional_open_domain")

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
