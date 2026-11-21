"""Non-rational functional derivations (`string`, `integer`, `boolean`) in the Soufflé test oracle helper."""

from __future__ import annotations

import shutil

import duckdb
import pytest

import souffle
from rezono_canon import canonical_bytes, sha256_hex
from rezono_checker import rules as checker_rules
from rezono_checker.canon import encode_key, sha256_json
from rezono_checker.check import check, check_epoch
from rezono_compiler import rules as ir, rules_sql


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


def test_propagated_invalid_colliding_with_multiple_known_candidates_yields_multiple_values(tmp_path):
    """When a propagated invalid state collides with two distinct known candidates on a
    non-rational functional relation, SQL, Soufflé, and the independent checker all agree
    on `invalid / multiple_values` (decisions/language-rezono-1.md §4)."""
    doc = {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "group_dom", "role": "base", "key": [_col("g")]},
            {
                "name": "src_raw", "role": "base",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {"name": "direct_cand", "role": "base", "key": [_col("g"), _col("n", "integer")]},
            {
                "name": "src_state", "role": "derived", "module": "core", "explain": "on_demand",
                "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")],
            },
            {
                "name": "mixed_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("src_state_r", "src_state", ["?g", "?id", "?st", "?rsn", "?n"],
                  [_lit("src_raw", "?g", "?id", "?st", "?rsn", "?n")], stratum="1"),
            _rule("mixed_agg_r", "mixed_val", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="2",
                  aggregates=[{"relation": "src_state", "terms": ["?g", "_", "_", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "1"}]),
            _rule("mixed_direct_r", "mixed_val", ["?g", "?n"],
                  [_lit("group_dom", "?g"), _lit("direct_cand", "?g", "?n")], stratum="2"),
        ],
    }
    prog = ir.load(doc, require_witness=False)

    # 1. Soufflé Datalog lowering: conflict (`multiple_values`) takes precedence over MaxSt = 3.
    dl = souffle.program(prog)
    assert 'mixed_val(K0_, "invalid", "multiple_values", 0) :- Func_mixed_val_Conflict(K0_).' in dl
    assert (
        'mixed_val(K0_, "invalid", Rsn_, 0) :- Func_mixed_val_MaxSt(K0_, 3), '
        '!Func_mixed_val_Conflict(K0_), Func_mixed_val_MinRsn(K0_, 3, Rsn_).'
    ) in dl
    assert "MaxSt_ < 3" not in dl

    facts = {
        "group_dom": [("g_mix",), ("g_prop_only",)],
        "src_raw": [
            ("g_mix", "m1", "invalid", "bad_input", 0),
            ("g_prop_only", "m1", "invalid", "bad_input", 0),
        ],
        "direct_cand": [("g_mix", 10), ("g_mix", 20)],
    }

    # 2. DuckDB SQL evaluation: g_mix -> invalid/multiple_values; g_prop_only -> invalid/bad_input.
    con = duckdb.connect()
    for ddl in rules_sql.duckdb_tables(prog):
        con.execute(ddl)
    con.executemany('INSERT INTO "group_dom" VALUES (?)', facts["group_dom"])
    con.executemany('INSERT INTO "src_raw" VALUES (?, ?, ?, ?, ?)', facts["src_raw"])
    con.executemany('INSERT INTO "direct_cand" VALUES (?, ?)', facts["direct_cand"])
    for stmt in rules_sql.duckdb_program(prog, witnesses=False):
        con.execute(stmt)
    got_sql = set(con.execute('SELECT * FROM "mixed_val"').fetchall())
    assert got_sql == {
        ("g_mix", "invalid", "multiple_values", 0),
        ("g_prop_only", "invalid", "bad_input", 0),
    }

    # 3. Soufflé oracle execution (when souffle binary is available): exact match with SQL.
    if shutil.which("souffle") is not None:
        got_souffle = souffle.run(prog, facts, tmp_path)
        assert got_souffle["mixed_val"] == {
            ("g_mix", "invalid", "multiple_values", "0"),
            ("g_prop_only", "invalid", "bad_input", "0"),
        }

    # 4. Independent checker verification: accepts the exact SQL/Soufflé rows in check_epoch() and check().
    def _ref(rel: str, *parts: str) -> dict:
        return {"relation": rel, "key": encode_key(list(parts))}

    src_rows = [
        ["g_mix", "m1", "invalid", "bad_input", "0"],
        ["g_prop_only", "m1", "invalid", "bad_input", "0"],
    ]
    rows = {
        "group_dom": [["g_mix"], ["g_prop_only"]],
        "src_raw": src_rows,
        "direct_cand": [["g_mix", "10"], ["g_mix", "20"]],
        "src_state": src_rows,
        "mixed_val": [
            ["g_mix", "invalid", "multiple_values", ""],
            ["g_prop_only", "invalid", "bad_input", ""],
        ],
    }

    def _agg_entry(g: str) -> dict:
        members = sorted((encode_key(r), r[2]) for r in src_rows if r[0] == g)
        return {
            "relation": "src_state",
            "position": 0,
            "group_key": encode_key([g]),
            "count": len(members),
            "contributors_sha256": sha256_json([[k, st] for k, st in members]),
            "result": "invalid",
        }

    witnesses = [
        *[
            {
                "conclusion": _ref("src_state", *r),
                "rule_id": "src_state_r",
                "bindings": [
                    {"variable": "?g", "value": r[0]},
                    {"variable": "?id", "value": r[1]},
                    {"variable": "?st", "value": r[2]},
                    {"variable": "?rsn", "value": r[3]},
                    {"variable": "?n", "value": r[4]},
                ],
                "premises": [{"row": _ref("src_raw", *r), "polarity": "positive", "stratum": 0}],
            }
            for r in src_rows
        ],
        {
            "conclusion": _ref("mixed_val", "g_mix", "invalid", "multiple_values", ""),
            "rule_id": "mixed_agg_r",
            "bindings": [{"variable": "?g", "value": "g_mix"}],
            "premises": [
                {"row": _ref("group_dom", "g_mix"), "polarity": "positive", "stratum": 0},
                {"row": _ref("direct_cand", "g_mix", "10"), "polarity": "positive", "stratum": 0},
                {"row": _ref("direct_cand", "g_mix", "20"), "polarity": "positive", "stratum": 0},
            ],
            "aggregates": [_agg_entry("g_mix")],
        },
        {
            "conclusion": _ref("mixed_val", "g_prop_only", "invalid", "bad_input", ""),
            "rule_id": "mixed_agg_r",
            "bindings": [{"variable": "?g", "value": "g_prop_only"}],
            "premises": [{"row": _ref("group_dom", "g_prop_only"), "polarity": "positive", "stratum": 0}],
            "aggregates": [_agg_entry("g_prop_only")],
        },
    ]

    loaded = checker_rules.load_rules(doc)
    snaps = {rel: canonical_bytes([{"key": row} for row in sorted(rs)]) for rel, rs in rows.items()}
    manifest = {
        "id": "m-souffle-fn-collision-1",
        "snapshots": [
            {"relation": rel, "role": "all", "complete": True, "uri": rel, "format": "json",
             "sha256": sha256_hex(body)}
            for rel, body in sorted(snaps.items())
        ],
    }
    derived = checker_rules.derived_relations(doc, loaded)

    epoch_rep = check_epoch(witnesses, manifest, loaded, snaps.__getitem__, derived=derived)
    assert epoch_rep["valid"], epoch_rep["findings"]

    mix_w = witnesses[2]
    single_rep = check(
        {"manifest_id": manifest["id"], "root": mix_w["conclusion"], "witnesses": [mix_w]},
        manifest, loaded, snaps.__getitem__,
    )
    assert single_rep["valid"], single_rep["findings"]
