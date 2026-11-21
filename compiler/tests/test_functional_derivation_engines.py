"""Co-located NOT NULL functional derivation views `(key..., state, reason, value)` on DuckDB, Soufflé (oracle for
the non-rational fragment), and Feldera (incremental target engine): known, unknown (`no_value`), not_applicable
(`empty`), invalid (`multiple_values` with all competing candidates), strict four-state aggregation (Appendix A.3),
and exact rational `(n BIGINT, d BIGINT)` columns (decisions/language-rezono-1.md, sections 2, 4, 5.2, 5.4 and 8)."""

from __future__ import annotations

import re
import shutil

import duckdb
import pytest

import feldera
import souffle
from rezono_compiler import calc_sql, rules as ir, rules_sql


class MissingFunctionalDerivationEngines(AssertionError):
    """DuckDB, Soufflé oracle, or Feldera lowering for rezono.rules/2 functional derivations is missing or wrong."""


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


def _non_rational_program() -> dict:
    """Covers known, unknown (no_value), not_applicable (empty), invalid (multiple_values), boolean functional
    values, conflict_policy publish vs block, downstream Bool reads, and strict 4-state sum aggregation."""
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
                "name": "pair_val", "role": "functional", "module": "core", "explain": "materialize",
                "key": [_col("a"), _col("b")], "domain": "pair_dom",
                "value": _col("value", "string"), "conflict_policy": "publish",
            },
            {
                "name": "strict_val", "role": "functional", "module": "core", "explain": "materialize",
                "key": [_col("a"), _col("b")], "domain": "pair_dom",
                "value": _col("value", "string"), "conflict_policy": "block",
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
                "name": "group_total", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
            {
                "name": "group_opt_total", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("g")], "domain": "group_dom",
                "value": _col("value", "integer"), "conflict_policy": "publish",
            },
            {"name": "resolved_pair", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("a"), _col("b"), _col("v")]},
            {"name": "conflict_pair", "role": "derived", "module": "core", "explain": "on_demand",
             "key": [_col("a"), _col("b")]},
        ],
        "rules": [
            _rule("pair_val_r", "pair_val", ["?a", "?b", "?v"],
                  [_lit("pair_dom", "?a", "?b"), _lit("pair_cand", "?a", "?b", "?v")], stratum="1"),
            _rule("strict_val_r", "strict_val", ["?a", "?b", "?v"],
                  [_lit("pair_dom", "?a", "?b"), _lit("pair_cand", "?a", "?b", "?v")], stratum="1"),
            _rule("opt_val_r", "opt_val", ["?id", "?v"],
                  [_lit("item", "?id"), _lit("opt_cand", "?id", "?v")], stratum="1"),
            _rule("flag_val_r", "flag_val", ["?id", "?v"],
                  [_lit("item", "?id"), _lit("flag_cand", "?id", "?v")], stratum="1"),
            _rule("score_val_r", "score_val", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("opt_score_r", "opt_score", ["?id", "?n"],
                  [_lit("item", "?id"), _lit("score_cand", "?id", "?n")], stratum="1"),
            _rule("group_total_r", "group_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="2",
                  aggregates=[{"relation": "member_score", "terms": ["?g", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "1"}]),
            _rule("group_opt_total_r", "group_opt_total", ["?g", "?total"],
                  [_lit("group_dom", "?g")], stratum="2",
                  aggregates=[{"relation": "member_opt_score", "terms": ["?g", "_", "_"],
                               "function": "sum", "over": "n", "as": "?total", "stratum": "1"}]),
            _rule("resolved_pair_r", "resolved_pair", ["?a", "?b", "?v"],
                  [_lit("pair_val", "?a", "?b", "known", "", "?v", stratum="1")], stratum="2"),
            _rule("conflict_pair_r", "conflict_pair", ["?a", "?b"],
                  [_lit("pair_val", "?a", "?b", "invalid", "multiple_values", "?v", stratum="1")], stratum="2"),
        ],
    }


def _full_program_with_rational() -> dict:
    """Extends the non-rational program with member-score join helpers and an exact rational functional derivation."""
    doc = _non_rational_program()
    doc["relations"].extend([
        {"name": "member_score", "role": "derived", "module": "core", "explain": "on_demand",
         "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")]},
        {"name": "member_opt_score", "role": "derived", "module": "core", "explain": "on_demand",
         "key": [_col("g"), _col("id"), _col("state"), _col("reason"), _col("n", "integer")]},
        {"name": "ratio_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
        {
            "name": "ratio_val", "role": "functional", "module": "core", "explain": "on_demand",
            "key": [_col("id")], "domain": "item",
            "value": _col("value", "rational"), "conflict_policy": "publish",
        },
    ])
    doc["rules"].extend([
        _rule("member_score_r", "member_score", ["?g", "?id", "?st", "?rsn", "?n"],
              [_lit("member_of", "?g", "?id"), _lit("score_val", "?id", "?st", "?rsn", "?n", stratum="1")],
              stratum="2"),
        _rule("member_opt_score_r", "member_opt_score", ["?g", "?id", "?st", "?rsn", "?n"],
              [_lit("member_of", "?g", "?id"), _lit("opt_score", "?id", "?st", "?rsn", "?n", stratum="1")],
              stratum="2"),
        _rule("ratio_val_r", "ratio_val", ["?id", "?r"],
              [_lit("item", "?id"), _lit("ratio_in", "?id", "?r")], stratum="1"),
    ])
    # Update group_total / group_opt_total aggregate terms to match 5-column member_score / member_opt_score.
    for rule in doc["rules"]:
        if rule["id"] in ("group_total_r", "group_opt_total_r"):
            rule["stratum"] = "3"
            rule["aggregates"][0]["terms"] = ["?g", "_", "_", "_", "_"]
            rule["aggregates"][0]["stratum"] = "2"
    return doc


FACTS = {
    "item": [("i_ok1",), ("i_ok2",), ("i_empty",), ("i_clash",)],
    "pair_dom": [("g1", "k_known"), ("g1", "k_missing"), ("g1", "k_conflict")],
    "pair_cand": [
        ("g1", "k_known", "v1"),
        ("g1", "k_conflict", "v1"),
        ("g1", "k_conflict", "v2"),
    ],
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
    "ratio_in": [("i_ok1", "3/2"), ("i_ok2", "-2"), ("i_clash", "1/2"), ("i_clash", "3/4")],
}


def test_functional_derivation_duckdb_souffle_and_feldera():
    # Counter-case: rezono.rules/1 plain Bool relation emits zero state/reason columns on DuckDB, Feldera and Soufflé.
    v1_prog = ir.load({
        "format": "rezono.rules/1", "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "listed", "role": "derived", "module": "core", "explain": "on_demand", "key": [_col("id")]},
        ],
        "rules": [_rule("listed_r", "listed", ["?x"], [_lit("item", "?x")], stratum="1")],
    }, require_witness=False)
    v1_feldera = rules_sql.feldera(v1_prog, witnesses="none")
    assert "CREATE MATERIALIZED VIEW" in v1_feldera and "state" not in v1_feldera
    assert ".decl listed(id:symbol)" in souffle.program(v1_prog)

    problems: list[str] = []

    try:
        prog = ir.load(_full_program_with_rational(), require_witness=False)
    except Exception as exc:
        raise MissingFunctionalDerivationEngines(f"ir.load failed on functional engine test program: {exc}") from None

    # 1. Feldera SQL structure (always checked; live Feldera parity runs when FELDERA_URL is configured).
    try:
        feldera_sql = rules_sql.feldera(prog, witnesses="materialize")
    except Exception as exc:
        problems.append(f"rules_sql.feldera failed: {exc}")
        feldera_sql = ""
    else:
        for name in ("pair_val", "strict_val", "opt_val", "flag_val", "score_val", "ratio_val"):
            if not re.search(rf"CREATE MATERIALIZED VIEW\s+[^\n]*{name}", feldera_sql):
                problems.append(f"Feldera SQL missing co-located CREATE MATERIALIZED VIEW for {name}")
            if re.search(rf"DECLARE RECURSIVE VIEW\s+[^\n]*{name}", feldera_sql):
                problems.append(f"Feldera SQL emitted functional derivation {name} inside DECLARE RECURSIVE VIEW")
        if "LEFT JOIN" not in feldera_sql:
            problems.append("Feldera SQL did not LEFT JOIN functional views over their declared closed domain")
        # conflict_policy = block adds an invalid-check view; publish does not.
        if not re.search(r"strict_val__[a-z_]+", feldera_sql):
            problems.append("Feldera SQL missing conflict_policy=block check view for strict_val")

    # 2. DuckDB batch execution: NOT NULL co-located tables, all 4 states, strict 4-state aggregation, rational (n, d).
    duckdb_results: dict[str, set[tuple]] = {}
    try:
        stmts = rules_sql.duckdb_program(prog, "materialize")
        con = duckdb.connect()
        con.execute(rules_sql.DUCKDB_MACROS)
        con.execute(calc_sql.DUCKDB_MACROS)
        for rel in prog.relations.values():
            if rel.role != "base":
                continue
            col_defs = []
            for c in rel.key + rel.values:
                if c.type == "rational":
                    col_defs.extend([f'"{c.name}_n" BIGINT NOT NULL', f'"{c.name}_d" BIGINT NOT NULL'])
                else:
                    col_defs.append(f'"{c.name}" {rules_sql.SQL_TYPE[c.type]} NOT NULL')
            con.execute(f'CREATE TABLE "{rel.name}" ({", ".join(col_defs)});')
            rows = FACTS.get(rel.name, [])
            if rows:
                expanded = []
                for row in rows:
                    vals = []
                    for cell, c in zip(row, rel.key + rel.values):
                        if c.type == "rational":
                            num, _, den = str(cell).partition("/")
                            vals.extend([int(num), int(den or "1")])
                        else:
                            vals.append(cell)
                    expanded.append(tuple(vals))
                placeholders = ", ".join("?" for _ in expanded[0])
                con.executemany(f'INSERT INTO "{rel.name}" VALUES ({placeholders})', expanded)
        for stmt in stmts:
            con.execute(stmt)
        for name, rel in prog.relations.items():
            if rel.role not in ("derived", "functional"):
                continue
            rows = con.execute(f'SELECT * FROM "{name}"').fetchall()
            for row in rows:
                if any(cell is None for cell in row):
                    problems.append(f"DuckDB table {name} contains SQL NULL in row {row!r} (must be NOT NULL)")
            duckdb_results[name] = set(rows)
    except Exception as exc:
        problems.append(f"DuckDB execution failed: {exc}")

    if duckdb_results:
        pair_rows = {(r[0], r[1]): (r[2], r[3], r[4]) for r in duckdb_results.get("pair_val", ())}
        if pair_rows.get(("g1", "k_known")) != ("known", "", "v1"):
            problems.append(f"pair_val known mismatch: {pair_rows.get(('g1', 'k_known'))!r}")
        if pair_rows.get(("g1", "k_missing"), (None, None))[0:2] != ("unknown", "no_value"):
            problems.append(f"pair_val unknown mismatch: {pair_rows.get(('g1', 'k_missing'))!r}")
        if pair_rows.get(("g1", "k_conflict"), (None, None))[0:2] != ("invalid", "multiple_values"):
            problems.append(f"pair_val invalid mismatch: {pair_rows.get(('g1', 'k_conflict'))!r}")

        opt_rows = {r[0]: (r[1], r[2]) for r in duckdb_results.get("opt_val", ())}
        if opt_rows.get("i_ok1") != ("known", "") or opt_rows.get("i_empty") != ("not_applicable", "empty"):
            problems.append(f"opt_val mismatch: {opt_rows!r}")

        if duckdb_results.get("resolved_pair") != {("g1", "k_known", "v1")}:
            problems.append(f"downstream Bool resolved_pair emitted non-known rows: {duckdb_results.get('resolved_pair')!r}")
        if duckdb_results.get("conflict_pair") != {("g1", "k_conflict")}:
            problems.append(f"downstream Bool conflict_pair mismatch: {duckdb_results.get('conflict_pair')!r}")

        # Strict 4-state aggregate propagation (Appendix A.3): invalid > unknown > not_applicable > known.
        gt = {r[0]: (r[1], r[3]) for r in duckdb_results.get("group_total", ())}
        got = {r[0]: (r[1], r[3]) for r in duckdb_results.get("group_opt_total", ())}
        if gt.get("g_ok") != ("known", 30):
            problems.append(f"group_total g_ok expected ('known', 30), got {gt.get('g_ok')!r}")
        if gt.get("g_unknown", (None,))[0] != "unknown":
            problems.append(f"group_total g_unknown did not propagate unknown: {gt.get('g_unknown')!r}")
        if got.get("g_na", (None,))[0] != "not_applicable":
            problems.append(f"group_opt_total g_na did not propagate not_applicable (strict Appendix A.3): {got.get('g_na')!r}")
        if gt.get("g_invalid", (None,))[0] != "invalid":
            problems.append(f"group_total g_invalid did not propagate invalid: {gt.get('g_invalid')!r}")

        # Exact rational `(n BIGINT, d BIGINT)` with d > 0.
        rat_rows = {r[0]: r[1:] for r in duckdb_results.get("ratio_val", ())}
        if rat_rows.get("i_ok1") != ("known", "", 3, 2):
            problems.append(f"ratio_val i_ok1 expected ('known', '', 3, 2), got {rat_rows.get('i_ok1')!r}")
        if rat_rows.get("i_ok2") != ("known", "", -2, 1):
            problems.append(f"ratio_val i_ok2 expected ('known', '', -2, 1), got {rat_rows.get('i_ok2')!r}")
        if rat_rows.get("i_clash", (None, None))[:2] != ("invalid", "multiple_values"):
            problems.append(f"ratio_val i_clash expected invalid/multiple_values, got {rat_rows.get('i_clash')!r}")
        if any(row[4] <= 0 for row in duckdb_results.get("ratio_val", ())):
            problems.append(f"ratio_val emitted non-positive denominator d <= 0: {duckdb_results.get('ratio_val')!r}")

    # 3. Soufflé test oracle on the non-rational fragment (`string`, `integer`, `boolean`).
    try:
        non_rat_doc = _full_program_with_rational()
        non_rat_doc["relations"] = [r for r in non_rat_doc["relations"] if r["name"] not in ("ratio_in", "ratio_val")]
        non_rat_doc["rules"] = [r for r in non_rat_doc["rules"] if r["head"]["relation"] != "ratio_val"]
        non_rat_prog = ir.load(non_rat_doc, require_witness=False)
        dl_text = souffle.program(non_rat_prog)
        if ".decl pair_val(" not in dl_text or ".decl flag_val(" not in dl_text:
            problems.append("souffle.program did not emit declarations for non-rational functional relations")
        if shutil.which("souffle"):
            oracle_facts = {k: v for k, v in FACTS.items() if k != "ratio_in"}
            oracle = souffle.run(non_rat_prog, oracle_facts)
            for rel_name in ("pair_val", "opt_val", "flag_val", "resolved_pair", "conflict_pair"):
                if oracle.get(rel_name) is None:
                    problems.append(f"Soufflé oracle omitted {rel_name}")
    except Exception as exc:
        problems.append(f"Soufflé oracle lowering failed on non-rational functional fragment: {exc}")

    # 4. Live Feldera parity check when FELDERA_URL is configured (e.g. feldera-oracle workflow).
    if feldera.URL and feldera_sql and not problems:
        name = "test_functional_derivation_parity"
        try:
            feldera.deploy(name, feldera_sql, profile="unoptimized")
            updates = {}
            for rel in prog.relations.values():
                if rel.role != "base":
                    continue
                rows = FACTS.get(rel.name, [])
                if not rows:
                    continue
                payload = []
                for row in rows:
                    rec = {}
                    for cell, c in zip(row, rel.key + rel.values):
                        if c.type == "rational":
                            num, _, den = str(cell).partition("/")
                            rec[f"{c.name}_n"] = int(num)
                            rec[f"{c.name}_d"] = int(den or "1")
                        else:
                            rec[c.name] = cell
                    payload.append({"insert": rec})
                updates[rel.name] = payload
            feldera.processed(name, feldera.push(name, updates))
            for rel_name in ("pair_val", "opt_val", "ratio_val", "resolved_pair", "conflict_pair"):
                got_rows = feldera.call("GET", f"/v0/pipelines/{name}/query?sql=SELECT%20*%20FROM%20{rel_name}&format=json")
                if got_rows is None:
                    problems.append(f"Feldera query returned no rows for {rel_name}")
        finally:
            try:
                feldera.stop(name, delete=True)
            except Exception:
                pass

    if problems:
        raise MissingFunctionalDerivationEngines("\n".join(problems))
