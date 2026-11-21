"""Non-rational functional derivations (`string`, `integer`, `boolean`) in the Soufflé test oracle helper."""

from __future__ import annotations

import shutil

import pytest

import souffle
from rezono_compiler import rules as ir


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


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


def _functional_program() -> dict:
    return {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "pair_dom", "role": "base", "key": [_col("a"), _col("b")]},
            {"name": "pair_cand", "role": "base", "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "opt_cand", "role": "base", "key": [_col("id"), _col("v")]},
            {"name": "flag_cand", "role": "base", "key": [_col("id"), _col("v", "boolean")]},
            {"name": "score_cand", "role": "base", "key": [_col("id"), _col("n", "integer")]},
            {"name": "group_dom", "role": "base", "key": [_col("g")]},
            {"name": "member_of", "role": "base", "key": [_col("g"), _col("id")]},
            {
                "name": "pair_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("a"), _col("b")], "domain": "pair_dom",
                "value": _col("value", "string"), "conflict_policy": "publish",
            },
            {
                "name": "opt_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "string"), "conflict_policy": "publish",
                "empty_state": "not_applicable", "empty_reason": "empty",
            },
            {
                "name": "flag_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "boolean"), "conflict_policy": "publish",
            },
            {
                "name": "score_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
            {
                "name": "opt_score", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "integer"), "conflict_policy": "publish",
                "empty_state": "not_applicable", "empty_reason": "empty",
            },
            {
                "name": "member_score", "role": "derived", "module": "core", "explain": "on_demand",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {
                "name": "member_opt_score", "role": "derived", "module": "core", "explain": "on_demand",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {
                "name": "group_total", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
            {
                "name": "group_opt_total", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
            {
                "name": "resolved_pair", "role": "derived", "module": "core", "explain": "on_demand",
                "key": [_col("a"), _col("b"), _col("v")],
            },
            {
                "name": "conflict_pair", "role": "derived", "module": "core", "explain": "on_demand",
                "key": [_col("a"), _col("b")],
            },
        ],
        "rules": [
            _rule("pair_val_r", "pair_val", ["?a", "?b", "?v"],
                  [_lit("pair_dom", "?a", "?b"), _lit("pair_cand", "?a", "?b", "?v")], stratum="1"),
            _rule("opt_val_r", "opt_val", ["?id", "?v"],
                  [_lit("item", "?id"), _lit("opt_cand", "?id", "?v")], stratum="1"),
            _rule("flag_val_r", "flag_val", ["?id", "?v"],
                  [_lit("item", "?id"), _lit("flag_cand", "?id", "?v")], stratum="1"),
            _rule("score_val_r", "score_val", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("opt_score_r", "opt_score", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("member_score_r", "member_score", ["?g", "?id", "?st", "?rsn", "?n"],
                  [_lit("member_of", "?g", "?id"), _lit("score_val", "?id", "?st", "?rsn", "?n", stratum="1")],
                  stratum="2"),
            _rule("member_opt_score_r", "member_opt_score", ["?g", "?id", "?st", "?rsn", "?n"],
                  [_lit("member_of", "?g", "?id"), _lit("opt_score", "?id", "?st", "?rsn", "?n", stratum="1")],
                  stratum="2"),
            _rule("group_total_r", "group_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="3",
                  aggregates=[{"relation": "member_score", "terms": ["?g", "_", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "2"}]),
            _rule("group_opt_total_r", "group_opt_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="3",
                  aggregates=[{"relation": "member_opt_score", "terms": ["?g", "_", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "2"}]),
            _rule("resolved_pair_r", "resolved_pair", ["?a", "?b", "?v"],
                  [_lit("pair_val", "?a", "?b", "known", "", "?v", stratum="1")], stratum="2"),
            _rule("conflict_pair_r", "conflict_pair", ["?a", "?b"],
                  [_lit("pair_val", "?a", "?b", "invalid", "multiple_values", "?v", stratum="1")], stratum="2"),
        ],
    }


def test_souffle_program_lowers_functional_declarations_and_rejects_rational():
    prog = ir.load(_functional_program(), require_witness=False)
    dl = souffle.program(prog)
    assert ".decl pair_val(a:symbol, b:symbol, state:symbol, reason:symbol, value:symbol)" in dl
    assert ".decl flag_val(id:symbol, state:symbol, reason:symbol, value:symbol)" in dl
    assert ".decl score_val(id:symbol, state:symbol, reason:symbol, value:number)" in dl
    assert ".decl group_total(g:symbol, state:symbol, reason:symbol, value:number)" in dl
    assert ".output pair_val" in dl and ".output flag_val" in dl

    rat_doc = {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "rate_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {
                "name": "ratio_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("ratio_r", "ratio_val", ["?id", "?r"], [_lit("item", "?id"), _lit("rate_in", "?id", "?r")], stratum="1"),
        ],
    }
    rat_prog = ir.load(rat_doc, require_witness=False)
    with pytest.raises(ValueError, match="rational"):
        souffle.program(rat_prog)


@pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
def test_souffle_run_evaluates_functional_derivations_and_strict_aggregates(tmp_path):
    prog = ir.load(_functional_program(), require_witness=False)
    facts = {
        "item": [("i_ok1",), ("i_ok2",), ("i_empty",), ("i_clash",)],
        "pair_dom": [("g1", "k_known"), ("g1", "k_missing"), ("g1", "k_conflict")],
        "pair_cand": [("g1", "k_known", "v1"), ("g1", "k_conflict", "v1"), ("g1", "k_conflict", "v2")],
        "opt_cand": [("i_ok1", "chosen"), ("i_ok2", "chosen")],
        "flag_cand": [("i_ok1", True), ("i_ok2", False), ("i_clash", True), ("i_clash", False)],
        "score_cand": [("i_ok1", 10), ("i_ok2", 20), ("i_clash", 5), ("i_clash", 7)],
        "group_dom": [("g_ok",), ("g_unknown",), ("g_na",), ("g_invalid",)],
        "member_of": [
            ("g_ok", "i_ok1"), ("g_ok", "i_ok2"),
            ("g_unknown", "i_ok1"), ("g_unknown", "i_empty"),
            ("g_na", "i_ok1"), ("g_na", "i_empty"),
            ("g_invalid", "i_ok1"), ("g_invalid", "i_empty"), ("g_invalid", "i_clash"),
        ],
    }
    got = souffle.run(prog, facts, tmp_path)
    assert got["pair_val"] == {
        ("g1", "k_known", "known", "", "v1"),
        ("g1", "k_missing", "unknown", "no_value", ""),
        ("g1", "k_conflict", "invalid", "multiple_values", ""),
    }
    assert got["opt_val"] == {
        ("i_ok1", "known", "", "chosen"),
        ("i_ok2", "known", "", "chosen"),
        ("i_empty", "not_applicable", "empty", ""),
        ("i_clash", "not_applicable", "empty", ""),
    }
    assert got["flag_val"] == {
        ("i_ok1", "known", "", "true"),
        ("i_ok2", "known", "", "false"),
        ("i_empty", "unknown", "no_value", "false"),
        ("i_clash", "invalid", "multiple_values", "false"),
    }
    assert got["group_total"] == {
        ("g_ok", "known", "", "30"),
        ("g_unknown", "unknown", "no_value", "0"),
        ("g_na", "unknown", "no_value", "0"),
        ("g_invalid", "invalid", "multiple_values", "0"),
    }
    assert got["group_opt_total"] == {
        ("g_ok", "known", "", "30"),
        ("g_unknown", "not_applicable", "empty", "0"),
        ("g_na", "not_applicable", "empty", "0"),
        ("g_invalid", "invalid", "multiple_values", "0"),
    }
    assert got["resolved_pair"] == {("g1", "k_known", "v1")}
    assert got["conflict_pair"] == {("g1", "k_conflict")}
