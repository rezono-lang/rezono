"""Regression tests for rezono.rules/2 SQL lowering guards and access-boundary checks."""

from __future__ import annotations

import duckdb
import pytest

from rezono_compiler import calc_sql, rules as ir, rules_sql


def _col(name: str, typ: str = "string") -> dict:
    return {"name": name, "type": typ}


def _lit(rel: str, *terms: str, polarity: str = "positive", stratum: str = "0") -> dict:
    return {"relation": rel, "terms": list(terms), "polarity": polarity, "stratum": stratum}


def _rule(rid: str, head_rel: str, head_terms: list[str], body: list[dict], *,
          stratum: str = "1", module: str = "core") -> dict:
    return {
        "id": rid,
        "module": module,
        "stratum": stratum,
        "head": {"relation": head_rel, "terms": head_terms},
        "body": body,
        "origin": {"file": f"rules/{module}.rezono", "line": "1"},
    }


def test_rational_functional_invalid_denominator_and_overflow_mark_invalid():
    doc = {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "item", "role": "base", "key": [_col("id")]},
            {"name": "ratio_in", "role": "base", "key": [_col("id"), _col("r", "rational")]},
            {
                "name": "ratio_val", "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("id")], "domain": "item",
                "value": _col("value", "rational"), "conflict_policy": "block",
            },
        ],
        "rules": [
            _rule("ratio_val_r", "ratio_val", ["?id", "?r"],
                  [_lit("item", "?id"), _lit("ratio_in", "?id", "?r")], stratum="1"),
        ],
    }
    prog = ir.load(doc, require_witness=False)

    feldera_sql = rules_sql.feldera(prog, witnesses=False)
    assert "invalid_rational" in feldera_sql
    assert "ratio_val__invalid" in feldera_sql

    con = duckdb.connect()
    con.execute(calc_sql.DUCKDB_MACROS)
    for ddl in rules_sql.duckdb_tables(prog):
        con.execute(ddl)
    con.executemany(
        'INSERT INTO "item" VALUES (?)',
        [("i_ok",), ("i_zero_den",), ("i_neg_den",), ("i_overflow",), ("i_mixed_bad",), ("i_conflict",)],
    )
    con.executemany(
        'INSERT INTO "ratio_in" VALUES (?, ?, ?)',
        [
            ("i_ok", 3, 2),
            ("i_zero_den", 1, 0),
            ("i_neg_den", 1, -2),
            ("i_overflow", -(2**63), 1),
            ("i_mixed_bad", 1, 2),
            ("i_mixed_bad", 1, 0),
            ("i_conflict", 1, 2),
            ("i_conflict", 3, 4),
        ],
    )
    for stmt in rules_sql.duckdb_program(prog, witnesses=False):
        con.execute(stmt)

    rows = con.execute('SELECT * FROM "ratio_val"').fetchall()
    assert all(cell is not None for row in rows for cell in row)
    by_id = {row[0]: row[1:] for row in rows}
    assert by_id == {
        "i_ok": ("known", "", 3, 2),
        "i_zero_den": ("invalid", "invalid_rational", 0, 1),
        "i_neg_den": ("invalid", "invalid_rational", 0, 1),
        "i_overflow": ("invalid", "invalid_rational", 0, 1),
        "i_mixed_bad": ("invalid", "invalid_rational", 0, 1),
        "i_conflict": ("invalid", "multiple_values", 0, 1),
    }

    blocked = {row[0] for row in con.execute('SELECT * FROM "ratio_val__invalid"').fetchall()}
    assert blocked == {"i_zero_den", "i_neg_den", "i_overflow", "i_mixed_bad", "i_conflict"}


def test_parse_rational_normalizes_fractions_and_rejects_zero_denominator():
    assert rules_sql._parse_rational("2/4") == (1, 2)
    assert rules_sql._parse_rational("-2/-4") == (1, 2)
    assert rules_sql._parse_rational("2/-4") == (-1, 2)
    assert rules_sql._parse_rational("0/5") == (0, 1)
    assert rules_sql._parse_rational("-3") == (-3, 1)

    for bad in ("1/0", "0/0", "1/", "not_a_number", "1/2/3"):
        with pytest.raises(ir.IRError) as exc_info:
            rules_sql._parse_rational(bad)
        assert exc_info.value.code == "bad_constant"

    # Unreduced literal "2/4" in positive match, negative anti-join, and aggregate filter matches stored (1, 2).
    rels = {
        "item": ir.Relation("item", "base", (ir.Column("id", "string"),)),
        "rate": ir.Relation("rate", "base", (ir.Column("id", "string"), ir.Column("r", "rational"))),
        "matched": ir.Relation("matched", "derived", (ir.Column("id", "string"),), module="core", explain="on_demand"),
        "not_half": ir.Relation("not_half", "derived", (ir.Column("id", "string"),), module="core", explain="on_demand"),
        "half_cnt": ir.Relation(
            "half_cnt", "derived", (ir.Column("id", "string"), ir.Column("n", "integer")),
            module="core", explain="on_demand",
        ),
    }
    rules = {
        "matched_r": ir.Rule(
            "matched_r", "core", 1,
            ir.Atom("matched", ("?id",)),
            (ir.Literal(ir.Atom("rate", ("?id", "2/4")), "positive", 0),),
        ),
        "not_half_r": ir.Rule(
            "not_half_r", "core", 1,
            ir.Atom("not_half", ("?id",)),
            (
                ir.Literal(ir.Atom("item", ("?id",)), "positive", 0),
                ir.Literal(ir.Atom("rate", ("?id", "2/4")), "negative", 0),
            ),
        ),
        "half_cnt_r": ir.Rule(
            "half_cnt_r", "core", 1,
            ir.Atom("half_cnt", ("?id", "?n")),
            (ir.Literal(ir.Atom("item", ("?id",)), "positive", 0),),
            aggregates=(ir.Aggregate(ir.Atom("rate", ("?id", "2/4")), "count", None, "?n", 0),),
        ),
    }
    prog = ir.Program("sample", rels, rules, strata={"item": 0, "rate": 0, "matched": 1, "not_half": 1, "half_cnt": 1},
                      format=ir.FORMAT_V2)

    con = duckdb.connect()
    for ddl in rules_sql.duckdb_tables(prog):
        con.execute(ddl)
    con.executemany('INSERT INTO "item" VALUES (?)', [("a",), ("b",)])
    con.executemany('INSERT INTO "rate" VALUES (?, ?, ?)', [("a", 1, 2), ("b", 3, 4)])
    for stmt in rules_sql.duckdb_program(prog, witnesses=False):
        con.execute(stmt)

    assert con.execute('SELECT * FROM "matched"').fetchall() == [("a",)]
    assert con.execute('SELECT * FROM "not_half"').fetchall() == [("b",)]
    assert set(con.execute('SELECT * FROM "half_cnt"').fetchall()) == {("a", 1), ("b", 0)}


@pytest.mark.parametrize("fn", ["sum", "min", "max"])
def test_aggregate_over_rational_column_rejected_cleanly(fn):
    rels = {
        "grp": ir.Relation("grp", "base", (ir.Column("g", "string"),)),
        "rate": ir.Relation("rate", "base", (ir.Column("g", "string"), ir.Column("r", "rational"))),
        "out": ir.Relation(
            "out", "derived", (ir.Column("g", "string"), ir.Column("x", "integer")),
            module="core", explain="on_demand",
        ),
    }
    rule = ir.Rule(
        "agg_rat", "core", 1,
        ir.Atom("out", ("?g", "?x")),
        (ir.Literal(ir.Atom("grp", ("?g",)), "positive", 0),),
        aggregates=(ir.Aggregate(ir.Atom("rate", ("?g", "_")), fn, "r", "?x", 0),),
    )
    prog = ir.Program("sample", rels, {"agg_rat": rule}, strata={"grp": 0, "rate": 0, "out": 1}, format=ir.FORMAT_V2)

    with pytest.raises(ir.IRError) as exc_info:
        rules_sql.rule_select(prog, rule, dialect="duckdb")
    assert exc_info.value.code == "bad_aggregate"
    assert "rational" in str(exc_info.value)


def test_zero_rule_functional_relation_emits_valid_sql_with_empty_state():
    rels = {
        "item": ir.Relation("item", "base", (ir.Column("id", "string"),)),
        "empty_str": ir.Relation(
            "empty_str", "functional", (ir.Column("id", "string"),),
            module="core", explain="on_demand", domain="item",
            value=ir.Column("value", "string"), conflict_policy="publish",
        ),
        "empty_int": ir.Relation(
            "empty_int", "functional", (ir.Column("id", "string"),),
            module="core", explain="on_demand", domain="item",
            value=ir.Column("value", "integer"), conflict_policy="publish",
            empty_state="not_applicable", empty_reason="empty",
        ),
        "empty_bool": ir.Relation(
            "empty_bool", "functional", (ir.Column("id", "string"),),
            module="core", explain="on_demand", domain="item",
            value=ir.Column("value", "boolean"), conflict_policy="publish",
        ),
        "empty_rat": ir.Relation(
            "empty_rat", "functional", (ir.Column("id", "string"),),
            module="core", explain="on_demand", domain="item",
            value=ir.Column("value", "rational"), conflict_policy="block",
            empty_state="not_applicable", empty_reason="no_match",
        ),
    }
    strata = {"item": 0, "empty_str": 1, "empty_int": 1, "empty_bool": 1, "empty_rat": 1}
    prog = ir.Program("sample", rels, {}, strata=strata, format=ir.FORMAT_V2)

    feldera_sql = rules_sql.feldera(prog, witnesses=False)
    assert 'WITH "__cand" AS (\n\n)' not in feldera_sql
    assert "FROM (VALUES (1)) AS seed(n) WHERE FALSE" in feldera_sql

    con = duckdb.connect()
    for ddl in rules_sql.duckdb_tables(prog):
        con.execute(ddl)
    con.executemany('INSERT INTO "item" VALUES (?)', [("a",), ("b",)])
    for stmt in rules_sql.duckdb_program(prog, witnesses=False):
        con.execute(stmt)

    assert set(con.execute('SELECT * FROM "empty_str"').fetchall()) == {
        ("a", "unknown", "no_value", ""),
        ("b", "unknown", "no_value", ""),
    }
    assert set(con.execute('SELECT * FROM "empty_int"').fetchall()) == {
        ("a", "not_applicable", "empty", 0),
        ("b", "not_applicable", "empty", 0),
    }
    assert set(con.execute('SELECT * FROM "empty_bool"').fetchall()) == {
        ("a", "unknown", "no_value", False),
        ("b", "unknown", "no_value", False),
    }
    assert set(con.execute('SELECT * FROM "empty_rat"').fetchall()) == {
        ("a", "not_applicable", "no_match", 0, 1),
        ("b", "not_applicable", "no_match", 0, 1),
    }
    assert con.execute('SELECT * FROM "empty_rat__invalid"').fetchall() == []


@pytest.mark.parametrize("access_rel", ["may_read", "may_read_full"])
def test_access_relation_declared_functional_rejected(access_rel):
    doc = {
        "format": "rezono.rules/2",
        "pack": "sample",
        "relations": [
            {"name": "role", "role": "base", "key": [_col("id")]},
            {
                "name": access_rel, "role": "functional", "module": "core", "explain": "on_demand",
                "key": [_col("role")], "domain": "role",
                "value": _col("allowed", "boolean"), "conflict_policy": "publish",
            },
        ],
        "rules": [
            _rule("acc_fn_r", access_rel, ["?r", "true"], [_lit("role", "?r")], stratum="1"),
        ],
    }
    with pytest.raises(ir.IRError) as exc_info:
        ir.load(doc, require_witness=False)
    assert exc_info.value.code == "access_depends_on_functional"
