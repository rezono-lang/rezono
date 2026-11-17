"""Test helpers for calculation rules: run a program on DuckDB and read every rule's value."""

from __future__ import annotations

import datetime
import json

import duckdb

from rezono_compiler import calc, calc_sql, emit, rules_sql, seal
from rezono_compiler import rules as ir
from rezono_compiler.calc import NUMBER, Program, derived_relations
from rezono_compiler.pack import Pack


def connect(pack: Pack, prog: Program, rows: dict[str, list[tuple]]):
    """A DuckDB database with the pack's tables, the calc macros and the rows loaded, then the rules
    (M2) and the calculation rules computed."""
    db = duckdb.connect()
    db.execute(emit.tables(pack))
    db.execute(calc_sql.duckdb_prelude())
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(pack).items()}
    for table, rs in sorted((params | rows).items()):
        if rs:
            db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    for name, body in seal.views(pack):  # refused and accepted input: the rules read `<kind>__accepted`
        db.execute(f"CREATE VIEW {emit.q(name)} AS {body}")
    rules = ir.load(pack.rules) if pack.rules else None
    selections = rules.calc_inputs() if rules else []
    # Rules that read a calculation result run after it, as batch/rules-late.sql does (emit.rules).
    before, after = rules.partition_at_calc(selections, calc_sql.derived_reads(prog)) if selections else (None, None)
    if rules:
        for statement in rules_sql.duckdb_program(rules, relations=before):
            db.execute(statement)
    db.execute(calc_sql.duckdb_body(prog))
    if selections:
        for statement in calc_sql.duckdb_rule_inputs(selections) + rules_sql.duckdb_program(rules, relations=after):
            db.execute(statement)
    return db


def derived_rows(db, pack: Pack) -> dict[str, list[tuple]]:
    """The rows of the derived relations: input to the reference, which checks the calculation, not M2."""
    return {name: db.execute(f"SELECT * FROM {emit.q(name)}").fetchall() for name in derived_relations(pack)}


def value_text(typ: str, state: str, n: int, d: int, b: bool) -> str:
    if state != "known":
        return ""
    if typ != NUMBER:
        return "true" if b else "false"
    # As written, not through Fraction: a fraction that is not in lowest terms must show up as a difference.
    return str(n) if d == 1 else f"{n}/{d}"


def results(db, prog: Program) -> dict[str, dict]:
    """Per rule and subject: (state, value text, reason, definition, version), as the oracle gives it."""
    out = {}
    for rule in prog.rules:
        got = db.execute(f"SELECT subject, state, n, d, b, reason, definition, version FROM {emit.q(prog.engine[rule])}").fetchall()
        out[rule] = {s: (st, value_text(prog.types[rule], st, n, d, b), r, df, v) for s, st, n, d, b, r, df, v in got}
        assert len(out[rule]) == len(got), f"{rule}: one row per subject"
    return out


def run(pack: Pack, prog: Program, rows: dict[str, list[tuple]]) -> dict[str, dict]:
    return results(connect(pack, prog, rows), prog)


def run_both(pack: Pack, prog: Program, doc: dict, rows: dict[str, list[tuple]]) -> tuple[dict, dict]:
    """(DuckDB, the reference), on the same rows; the reference also gets the derived relations."""
    from calcoracle import Oracle

    db = connect(pack, prog, rows)
    oracle = Oracle(pack, doc, rows | derived_rows(db, pack), concept_types(prog))
    assert witness_results(db, prog) == oracle.witnesses()  # the steps of every evaluation
    assert checked(db, prog) == []  # and the checker recomputes each of them on its own
    return results(db, prog), oracle.results()


def snapshots(db, prog: Program) -> dict[str, list[tuple]]:
    """The database as complete snapshots: every table by its rows as key parts, a calculation view as
    (subject, value, state, reason)."""
    views = {prog.engine[r]: prog.types[r] for r in prog.rules} | {v.engine: prog.types[v.rule] for v in prog.versions.values()}
    out: dict[str, list[tuple]] = {}
    for (name,) in db.execute("SELECT table_name FROM information_schema.tables ORDER BY table_name").fetchall():
        out[name] = [(str(r[0]), value_text(views[name], r[4], *r[1:4]), r[4], r[5]) if name in views
                     else tuple(cell_text(v) for v in r) for r in db.execute(f"SELECT * FROM {emit.q(name)}").fetchall()]
    return out


def checked(db, prog: Program, witnesses: list | None = None) -> list[dict]:
    """The checker's findings on every witness, against the database as complete snapshots (`snapshots`) and
    ir/calc.json as written."""
    from rezono_checker import calc as checker
    from rezono_checker.canon import encode_key

    snapshot = {name: {encode_key(parts): (parts, {}) for parts in rows} for name, rows in snapshots(db, prog).items()}
    ir_doc = json.loads(json.dumps(calc.to_doc(prog)))
    witnesses = calc_sql.witnesses(db, prog) if witnesses is None else witnesses
    return checker.check(witnesses, ir_doc, lambda relation: snapshot.get(relation, {}))


def cell_text(v) -> str:
    """As the publisher writes a cell: an integer as decimal text, a boolean as true/false, a date as ISO."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, datetime.date):
        return v.isoformat()
    return str(v)


def witness_results(db, prog: Program) -> dict[str, dict]:
    """Per rule (and per version named as rule@version) and subject: (version, definition, steps), as
    the oracle gives it, read from the witnesses (calc_sql.witnesses)."""
    names = {prog.engine[r]: r for r in prog.rules} | {v.engine: vid for vid, v in prog.versions.items()}
    out: dict[str, dict] = {}
    for w in calc_sql.witnesses(db, prog):
        subject = json.loads(w["conclusion"]["key"])[0]
        steps = tuple((s["path"], s["value"], s["state"], s["reason"]) + ((s["element"],) if "element" in s else ())
                      for s in w["steps"])
        assert subject not in out.get(names[w["conclusion"]["relation"]], {}), "one witness per row"
        out.setdefault(names[w["conclusion"]["relation"]], {})[subject] = (w["version"], w["definition"], steps)
    return out


def concept_types(prog: Program) -> dict[str, str]:
    return {f.id: f.type for f in prog.facts.values()}
