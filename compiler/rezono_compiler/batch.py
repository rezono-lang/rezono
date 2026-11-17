"""DuckDB as the batch backend (decision E1): load rows, compute the derived relations, read sets.

Used for publishing, CI and tests. It runs the same rule IR as Feldera, through the same translator
(rules_sql), so incremental and batch can be compared. DuckDB is an optional dependency (`[batch]`).
"""

import time

import duckdb

from . import rules_sql as sql
from .sqltext import q


def connect(prog, data, threads=None):
    """A database with the base relations of the program and their rows ({relation: [row, ...]}). A
    calculation selection the rules read is an input like a table: its rows, when `data` gives them, are what
    the rules read until `phases` computes the calculation in their place."""
    con = duckdb.connect()
    if threads:
        con.execute(f"SET threads = {int(threads)}")
    for s in sql.duckdb_tables(prog):
        con.execute(s)
    for name in prog.calc_inputs():
        rel = prog.relations[name]
        con.execute(f"CREATE TABLE {q(sql.relation_source(rel))} ("
                    + ", ".join(f"{q(c.name)} {sql.SQL_TYPE[c.type]} NOT NULL" for c in rel.key) + ");")
    for rel, rows in data.items():
        if rows and rel in prog.relations and prog.relations[rel].role in ("base", "calc"):
            con.executemany(f"INSERT INTO {q(sql.relation_source(prog.relations[rel]))} "
                            f"VALUES ({', '.join('?' * len(rows[0]))})", [list(r) for r in rows])
    return con


class BoundReached(ValueError):
    """A counter reached its explicit bound (#351 P6.2). The relation would be cut off there, so nothing is
    read from this run: reaching the bound is an error, never a relation with rows missing."""

    code = "bound_reached"


def compute(con, prog, witnesses=False, relations=None):
    """Recompute derived relations in evaluation order. Returns the seconds it took.

    The statements run one after the other and each one returns only when its table is complete,
    so the end of the last statement is the processing barrier, the same as a completion token.
    Raises BoundReached if a counter of the program reached its bound on these rows.
    """
    start = time.perf_counter()
    for s in sql.duckdb_program(prog, witnesses, relations):
        con.execute(s)
    for name, b in sorted(prog.bounds.items()):
        if relations is None or name in relations:
            for view, _ in sql.bound_checks(prog, name, "duckdb"):
                beyond = count(con, view)
                if beyond:
                    raise BoundReached(f"{BoundReached.code}: {name}: rule {b.rule} counted to its bound "
                                       f"({b.counter[1:]} <= {b.last}) and would add {beyond} more row(s), "
                                       f"so {name} is not whole; raise the bound or correct the facts")
    return time.perf_counter() - start


def phases(con, prog, calculation=None, step=None, compute=compute):
    """Compute the rules of `prog` on `con` with the calculation phase in its place (docs/compiler.md,
    calculation values in rules): the rules the calculation reads, the calculation, its selections as the
    typed inputs of the rules, then the rules that read them. Without a selection read: the rules, then the
    calculation. `step()` computes `calculation` (calc.Program) on `con`; by default its relations alone, on a
    database that holds what it reads. `compute` computes the rules of `relations`. Returns what `step`
    returns, None without a calculation. The one copy of the phase loop: the publisher, `explain` and the
    example tests call it."""
    from . import calc_sql

    if step is None:
        def step():
            con.execute(calc_sql.duckdb_body(calculation))
    inputs = prog.calc_inputs()
    if not inputs:
        compute(con, prog)
        return step() if calculation is not None else None
    before, after = prog.partition_at_calc(inputs, calc_sql.derived_reads(calculation))
    compute(con, prog, relations=before)
    out = step()
    for s in calc_sql.duckdb_rule_inputs(inputs):
        con.execute(s)
    compute(con, prog, relations=after)
    return out


def calculate(con, calculation, db, rows=None):
    """Compute `calculation` (calc.Program) on `con`, which holds the relations of the rules: the tables it
    reads that `con` does not hold come from `db` (`database`), then the macros, the evaluation date and the
    calculation's relations. Returns the calculation witnesses (decision W12), one per row of every view a
    publication holds (emit.calc_relations). With `rows`, the evaluation date and each of those views go into
    it as their snapshots hold them, (subject, value, state, reason) in canonical text. The one copy: the
    publisher, `explain` and the example tests call it."""
    from . import calc, calc_sql, emit
    from .seal import text

    doc = calc.to_doc(calculation)
    present = {r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()}
    needed = {calculation.subject_table, doc["parameters"], *doc.get("parameter_choice", {}).values(),
              *doc.get("inputs", {}).values()}
    needed |= {f.table for f in calculation.facts.values() if f.table and not f.derived}
    for t in sorted(needed & present - {""}):
        # A date a view's reading reads (RV-C27) is ISO text in the rules' table, which the calculation compares
        # as a date: the column takes the schema's type. The cast keeps every value and its text.
        have = {c[0]: c[1] for c in con.execute(f"DESCRIBE {q(t)}").fetchall()}
        for name, kind, *_ in db.execute(f"DESCRIBE {q(t)}").fetchall():
            if name in have and have[name] != kind:
                con.execute(f"ALTER TABLE {q(t)} ALTER {q(name)} TYPE {kind}")
    for t in sorted(needed - present - {""}):
        cols = db.execute(f"DESCRIBE {q(t)}").fetchall()
        con.execute(f"CREATE TABLE {q(t)} ({', '.join(f'{q(c[0])} {c[1]}' for c in cols)})")
        data = db.execute(f"SELECT * FROM {q(t)}").fetchall()
        if data:
            con.executemany(f"INSERT INTO {q(t)} VALUES ({', '.join('?' * len(cols))})", data)
    con.execute(calc_sql.duckdb_prelude())
    as_of = calc_sql.rows(calculation)[calc_sql.AS_OF]
    if as_of:
        con.executemany(f"INSERT INTO {q(calc_sql.AS_OF)} VALUES (?, ?, ?)",
                        [(a["id"], a["valid_at"], a["known_at"]) for a in as_of])
    con.execute(calc_sql.duckdb_body(calculation))
    if rows is not None:
        rows[calc_sql.AS_OF] = sorted({tuple(text(v) for v in r)
                                       for r in con.execute(f"SELECT * FROM {q(calc_sql.AS_OF)}").fetchall()})
        types = ({calculation.engine[r]: calculation.types[r] for r in calculation.rules}
                 | {v.engine: calculation.types[v.rule] for v in calculation.versions.values()})
        for view in [r["id"] for r in emit.calc_relations(calculation)]:
            got = con.execute(f"SELECT subject, n, d, b, state, reason FROM {q(view)}").fetchall()
            rows[view] = sorted({(text(r[0]), calc_sql.value_text(types[view], r[4], *r[1:4]), r[4], r[5]) for r in got})
    return calc_sql.witnesses(con, calculation)


def database(model, rows):
    """A database of the pack's tables with its parameter rows and the fact rows `rows`: what a calculation
    reads (`calculate`)."""
    from . import emit

    db = duckdb.connect()
    db.execute(emit.tables(model))
    params = {t: [tuple(r.values()) for r in rs] for t, rs in emit.parameters(model).items()}
    for table, rs in sorted((params | rows).items()):
        if rs:
            db.executemany(f"INSERT INTO {q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
    return db


def run(model, prog, rows, calculation=None):
    """A database with the rules of `prog` computed on the fact rows `rows` of `model`, and `calculation`
    in its phase (`phases`): what `explain` and the example tests read. Returns the database, the calculation
    witnesses and the rows of the calculation's views with its evaluation date (`calculate`); without a
    calculation, no witnesses and no rows."""
    from . import scenarios

    con, calculated = connect(prog, scenarios.rule_rows(model, prog, rows)), {}
    witnesses = phases(con, prog, calculation, lambda: calculate(con, calculation, database(model, rows), calculated))
    return con, witnesses or [], calculated


def apply(con, prog, rel, row, op):
    cols = [c.name for c in prog.relations[rel].key + prog.relations[rel].values]
    table = q(sql.relation_source(prog.relations[rel]))
    if op == "insert":
        con.execute(f"INSERT INTO {table} VALUES ({', '.join('?' * len(row))})", list(row))
    else:
        con.execute(f"DELETE FROM {table} WHERE " + " AND ".join(f"{q(c)} = ?" for c in cols), list(row))


def read(con, prog, names=None):
    """Relations as sets of tuples of canonical text (an integer as decimal text). A calculation selection
    is read as the rules read it: its known whole numbers."""
    out = {}
    for name in names or prog.derived():
        table = q(sql.relation_source(prog.relations[name]) if name in prog.relations else name)
        out[name] = {tuple(str(v) for v in r) for r in con.execute(f"SELECT * FROM {table}").fetchall()}
    return out


def witnesses(con, prog, rule_ids=None):
    """θ per rule, as sorted tuples of canonical text in the order of rule.variables.

    Runs the witness query of each rule (the explain query of on_demand relations) on the final
    relations; the empty substitution is the empty tuple.
    """
    out = {}
    for rid in sorted(rule_ids or prog.rules):
        rule = prog.rules[rid]
        rows = con.execute(sql.witness_select(prog, rule, "duckdb")).fetchall()
        out[rid] = sorted({() if not rule.variables else tuple(str(v) for v in r) for r in rows})
    return out


def count(con, name):
    return con.execute(f"SELECT COUNT(*) FROM {q(name)}").fetchone()[0]
