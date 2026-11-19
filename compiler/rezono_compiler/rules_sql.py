"""Rule IR -> SQL, for Feldera (incremental views) and DuckDB (batch tables). A small translator.

One SELECT per rule; the rules of a relation are a UNION, so the relation is a set.
- positive literal: a table in FROM, equalities in WHERE;
- negative literal: an anti-join, LEFT JOIN on the bound terms and the row kept where the join found
  nothing (`IS NULL` on a key column; every column is NOT NULL). Not a correlated NOT EXISTS: Feldera's
  planner (Calcite) cannot always decorrelate one, for example when the negated relation itself negates
  ("Not yet implemented: LEFT JOIN UNNEST"), so the engine SQL has no correlated subquery at all;
- aggregate: a GROUP BY subquery on the group key, LEFT JOIN with COALESCE(.., 0) for count and sum
  (an empty group gives 0, as in Soufflé), an inner JOIN for min and max (an empty group gives nothing).
  A body of aggregates only has no group key: the first subquery, without GROUP BY, is the FROM;
- condition and assignment: an expression. `div` truncates toward zero, as Feldera's `/` on BIGINT does
  (Feldera is the reference, E10). DuckDB's `/` gives a DOUBLE, so the batch backend divides with the macro
  `rezono_quotient` on 128 bits (`DUCKDB_MACROS`). The divisor is a non-zero constant (the IR checks it), so no
  engine ever divides by zero;
- a condition with compare_as (decisions/ordered-rule-scalars.md): on DuckDB an explicit comparison of the
  UTF-8 bytes, of the text or of the validated UTC key. Feldera's collation has no evidence yet, so the
  Feldera translation refuses such a rule rather than compare raw text;
- recursion (linear, one relation): Feldera DECLARE RECURSIVE VIEW; DuckDB WITH RECURSIVE ... UNION;
- a counter with an explicit bound (rules.Bound): no recursion on either engine. The rule is
  unrolled into one level per time it can fire, and what it would add beyond the bound is the check
  `<relation>__exhausted`: reaching the bound is a red check, never a relation cut off in silence.

Witness relations (contracts/rules.yaml): per rule a view with one column per variable, the same FROM
and WHERE as the rule. It reads the final relations, so it is never part of a recursion.
"""

from dataclasses import replace

from . import feldera_names
from .rules import BOOLEAN, Condition, calc_input_table, const_type, is_var, untyped_conditions, upper
from .sqltext import literal, q

OPS = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+", "sub": "-", "mul": "*", "div": "/"}
SQL_TYPE = {"string": "VARCHAR", "integer": "BIGINT", "boolean": "BOOLEAN"}
# Integer division truncated toward zero, on the absolute values, so it does not depend on how `//` rounds a
# negative operand; HUGEINT, so that abs(-2^63) fits. Only the quotient -2^63 / -1 does not fit a BIGINT.
DUCKDB_MACROS = ("CREATE OR REPLACE MACRO rezono_quotient(a, b) AS CAST(CASE WHEN (a < 0) = (b < 0) "
                 "THEN abs(a::HUGEINT) // abs(b::HUGEINT) ELSE -(abs(a::HUGEINT) // abs(b::HUGEINT)) END AS BIGINT);")


# A UTC instant as the request input spells it: YYYY-MM-DDTHH:mm:ss[.digits]Z, ASCII digits only.
UTC_PATTERN = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]+)?Z"
UTC_WHOLE = len("0001-01-01T00:00:00Z")


def utc_valid(x):
    """DuckDB: TRUE if the text is a UTC instant in years 0001 to 9999 on a Gregorian calendar day."""
    year, month, day = (f"TRY_CAST(substr({x}, {i}, {n}) AS INTEGER)" for i, n in ((1, 4), (6, 2), (9, 2)))
    leap = f"(({year} % 4 = 0 AND {year} % 100 <> 0) OR {year} % 400 = 0)"
    last = (f"CASE {month} WHEN 2 THEN CASE WHEN {leap} THEN 29 ELSE 28 END "
            "WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END")
    return (f"COALESCE(regexp_full_match({x}, {literal(UTC_PATTERN)}) AND {year} >= 1 "
            f"AND {day} <= {last}, FALSE)")


def utc_key(x):
    """DuckDB: the comparison key of a valid UTC instant. Without the terminal Z, trailing zeros of the
    fraction and a fraction that becomes empty; its bytes order the instants exactly."""
    return (f"CASE WHEN length({x}) > {UTC_WHOLE} THEN rtrim(rtrim(substr({x}, 1, length({x}) - 1), '0'), '.') "
            f"ELSE substr({x}, 1, {UTC_WHOLE - 1}) END")


def typed_condition(c, left, right):
    """DuckDB: a condition with compare_as, an explicit comparison of bytes (decisions/ordered-rule-scalars.md)."""
    if c.compare_as == "binary_text":
        return f"encode({left}) {OPS[c.op]} encode({right})"
    return (f"({utc_valid(left)} AND {utc_valid(right)} "
            f"AND encode({utc_key(left)}) {OPS[c.op]} encode({utc_key(right)}))")


def lit_sql(term, typ):
    if typ == "integer":
        return f"CAST({int(term)} AS BIGINT)"
    if typ == "boolean":
        return "TRUE" if BOOLEAN[term] else "FALSE"
    return literal(term)


def var_col(v):
    return "v_" + v[1:]


EMPTY_SUBSTITUTION = "empty_substitution"


def relation_source(rel):
    """The physical SQL name of a logical rule relation."""
    return calc_input_table(rel.name) if rel.role == "calc" else rel.name


def witness_columns(rule):
    """The columns of a witness relation. SQL has no relation without columns, so the empty
    substitution (a rule without variables) is one row with the column empty_substitution = TRUE."""
    return [var_col(v) for v in rule.variables] or [EMPTY_SUBSTITUTION]


class RuleSQL:
    """The FROM/WHERE of one rule and the SQL expression of each variable."""

    def __init__(self, prog, rule, rename=None, dialect="feldera"):
        rename = rename or {}
        self.prog, self.rule = prog, rule
        self.frm, self.where, self.env, self.types = [], [], {}, {}
        for i, b in enumerate(x for x in rule.body if x.polarity == "positive"):
            rel = prog.relations[b.atom.relation]
            alias = f"t{i}"
            on = []
            self._match(b.atom.terms, rel.key, alias, on)
            # Split Feldera receives the exported logical name. DuckDB shares a database with the
            # original calculation, so its four-column projection needs a separate name.
            source = relation_source(rel) if dialect == "duckdb" else rel.name
            table = f"{q(rename.get(rel.name, source))} AS {alias}"
            if i == 0:
                self.frm.append(table)
                self.where += on
            else:
                self.frm.append(f"JOIN {table} ON {' AND '.join(on) or 'TRUE'}")
        for i, a in enumerate(rule.aggregates):
            self._aggregate(i, a)
        for s in rule.assignments:
            if s.op == "days":  # a view's reading: the engine's own date arithmetic, right to left
                # A text that is no calendar day written YYYY-MM-DD derives nothing: the cast is guarded by the
                # spelling and cannot fail, and a NULL result drops the row. A date column is read as its own text.
                text = f"CAST({self.term(s.left, 'string')} AS VARCHAR)"
                cast, match = ("TRY_CAST", "regexp_matches") if dialect == "duckdb" else ("SAFE_CAST", "RLIKE")
                left = f"CASE WHEN {match}({text}, '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$') THEN {cast}({text} AS DATE) END"
                right = f"DATE {lit_sql(s.right, 'string')}"
                diff = f"date_diff('day', {right}, {left})" if dialect == "duckdb" else f"TIMESTAMPDIFF(DAY, {right}, {left})"
                self.env[s.var], self.types[s.var] = f"CAST({diff} AS BIGINT)", "integer"
                self.where.append(f"{left} IS NOT NULL")
                continue
            left, right = self.term(s.left, "integer"), self.term(s.right, "integer")
            if s.op == "div" and dialect == "duckdb":
                self.env[s.var] = f"rezono_quotient({left}, {right})"
            else:
                self.env[s.var] = f"({left} {OPS[s.op]} {right})"
            self.types[s.var] = "integer"
        for c in rule.conditions:
            if c.compare_as is not None:
                if dialect != "duckdb":  # Feldera's collation and functions have no evidence yet
                    untyped_conditions(rule, f"{dialect} SQL")
                self.where.append(typed_condition(c, self.term(c.left, "string"), self.term(c.right, "string")))
                continue
            t = self.types.get(c.left) or self.types.get(c.right) or const_type(c.left)
            self.where.append(f"{self.term(c.left, t)} {OPS[c.op]} {self.term(c.right, t)}")
        for i, b in enumerate(x for x in rule.body if x.polarity == "negative"):
            rel = prog.relations[b.atom.relation]
            alias = f"n{i}"
            conds = [f"{alias}.{q(col.name)} = {self.term(t, col.type)}" for t, col in zip(b.atom.terms, rel.key)]
            self.frm.append(f"LEFT JOIN {q(rename.get(rel.name, rel.name))} AS {alias} ON {' AND '.join(conds) or 'TRUE'}")
            self.where.append(f"{alias}.{q(rel.key[0].name)} IS NULL")

    def _match(self, terms, cols, alias, where):
        for t, col in zip(terms, cols):
            expr = f"{alias}.{q(col.name)}"
            if is_var(t):
                if t in self.env:
                    where.append(f"{expr} = {self.env[t]}")
                else:
                    self.env[t], self.types[t] = expr, col.type
            else:
                where.append(f"{expr} = {lit_sql(t, col.type)}")

    def _aggregate(self, i, a):
        rel = self.prog.relations[a.atom.relation]
        alias = f"g{i}"
        keys, filters = [], []
        for t, col in zip(a.atom.terms, rel.key):
            if is_var(t):
                keys.append((t, col))
            elif t != "_":
                filters.append(f"{q(col.name)} = {lit_sql(t, col.type)}")
        fn = "COUNT(*)" if a.function == "count" else f"{a.function.upper()}({q(a.over)})"
        sel = [f"{q(col.name)} AS k{j}" for j, (_, col) in enumerate(keys)] + [f"CAST({fn} AS BIGINT) AS r"]
        sub = f"SELECT {', '.join(sel)} FROM {q(rel.name)}"
        if filters:
            sub += " WHERE " + " AND ".join(filters)
        if keys:
            sub += " GROUP BY " + ", ".join(q(col.name) for _, col in keys)
        elif a.function in ("min", "max"):
            sub += " HAVING COUNT(*) > 0"   # a global min or max over nothing has no conclusion, not NULL
        on = " AND ".join(f"{alias}.k{j} = {self.env[t]}" for j, (t, _) in enumerate(keys)) or "TRUE"
        if not self.frm:
            # A body of aggregates only: no literal to join to, so the first subquery is the FROM itself. It
            # has no key, hence no GROUP BY: one row for count and sum (over nothing: 0 and NULL, read as 0
            # below), one row or none for min and max.
            self.frm.append(f"({sub}) AS {alias}")
            self.env[a.var] = f"COALESCE({alias}.r, CAST(0 AS BIGINT))" if a.function in ("count", "sum") else f"{alias}.r"
        elif a.function in ("count", "sum"):
            self.frm.append(f"LEFT JOIN ({sub}) AS {alias} ON {on}")
            self.env[a.var] = f"COALESCE({alias}.r, CAST(0 AS BIGINT))"
        else:
            self.frm.append(f"JOIN ({sub}) AS {alias} ON {on}")
            self.env[a.var] = f"{alias}.r"
        self.types[a.var] = "integer"

    def term(self, t, typ):
        return self.env[t] if is_var(t) else lit_sql(t, typ)

    def from_where(self):
        return f"FROM {' '.join(self.frm)}" + (" WHERE " + " AND ".join(self.where) if self.where else "")

    def select(self, exprs_names):
        return f"SELECT DISTINCT {', '.join(f'{e} AS {q(n)}' for e, n in exprs_names)} {self.from_where()}"


def rule_select(prog, rule, rename=None, dialect="feldera"):
    rel = prog.relations[rule.head.relation]
    r = RuleSQL(prog, rule, rename, dialect)
    return r.select([(r.term(t, c.type), c.name) for t, c in zip(rule.head.terms, rel.key)])


def witness_select(prog, rule, dialect="feldera"):
    r = RuleSQL(prog, rule, dialect=dialect)
    if not rule.variables:
        return r.select([("TRUE", EMPTY_SUBSTITUTION)])
    return r.select([(r.term(v, r.types[v]), var_col(v)) for v in rule.variables])


def _base_tables(prog, names=None):
    out = []
    for rel in prog.relations.values():
        if rel.role != "base" or (names is not None and rel.name not in names):
            continue
        cols = [f"{q(c.name)} {SQL_TYPE[c.type]} NOT NULL" for c in rel.key + rel.values]
        out.append(f"CREATE TABLE {q(rel.name)} ({', '.join(cols)});")
    return out


def outcome_checks(prog, name):
    """The checks of a named outcome, as (view, SELECT): every element of its kind has a row and
    every row is an element of the kind (`<outcome>__total`), and one state per element (`<outcome>__state`).
    A row in either is a red check."""
    rel = prog.relations[name]
    if rel.outcome is None:
        return []
    e, kind = q(rel.key[0].name), prog.relations[rel.outcome]
    k = q(kind.key[0].name)
    # Anti-joins, as for negation (no correlated subquery in the engine SQL).
    total = (f"SELECT DISTINCT k.{k} AS {e} FROM {q(kind.name)} AS k\n"
             f"LEFT JOIN {q(name)} AS o ON o.{e} = k.{k} WHERE o.{e} IS NULL\n"
             f"UNION\nSELECT DISTINCT o.{e} FROM {q(name)} AS o\n"
             f"LEFT JOIN {q(kind.name)} AS k ON k.{k} = o.{e} WHERE k.{k} IS NULL")
    state = f"SELECT {e} FROM {q(name)} GROUP BY {e} HAVING COUNT(DISTINCT {q('state')}) > 1"
    return [(f"{name}__total", total), (f"{name}__state", state)]


def bound_checks(prog, name, dialect="feldera"):
    """The check of a counter with an explicit bound, as (view, SELECT): `<relation>__exhausted`
    holds the rows the counting rule would add where it stopped, read from the final relation with the bound
    turned round. A row is a red check: the count reached its bound, so the relation is not whole."""
    b = prog.bounds.get(name)
    if b is None:
        return []
    rule = prog.rules[b.rule]
    beyond = tuple(c for c in rule.conditions if upper(c, b.counter) is None) + (Condition("gt", b.counter, str(b.last)),)
    return [(f"{name}__exhausted", rule_select(prog, replace(rule, conditions=beyond), dialect=dialect))]


def checks(prog, name, dialect="feldera"):
    """Every check view of one derived relation, as (view, SELECT): a row in any of them is a red check."""
    return outcome_checks(prog, name) + bound_checks(prog, name, dialect)


def unrolled(prog, name, dialect="feldera"):
    """A counter with an explicit bound as a query without recursion: level 0 is the rules that start the
    count, level i the counting rule over level i - 1, and the relation is the union of the levels. The rule
    fires `levels` times at most (rules.Bound), so the next level is empty on every input and the union is the
    whole fixpoint of the rules as written."""
    b = prog.bounds[name]
    selects = ["\nUNION\n".join(rule_select(prog, r, dialect=dialect) for r in prog.rules_for(name) if r.id != b.rule)]
    selects += [rule_select(prog, prog.rules[b.rule], rename={name: f"{name}__{i}"}, dialect=dialect)
                for i in range(b.levels)]
    # Every select names its columns after the relation's key, so a level needs no column list (as the WITH of
    # the integrity views, which both engines read).
    levels = ",\n".join(f"{q(f'{name}__{i}')} AS (\n{s}\n)" for i, s in enumerate(selects))
    return f"WITH {levels}\n" + "\nUNION\n".join(f"SELECT * FROM {q(f'{name}__{i}')}" for i in range(len(selects)))


def wants_witness(prog, rule, witnesses):
    """witnesses: False (none), True (every rule) or "materialize" (rules of relations with explain: materialize)."""
    if witnesses == "materialize":
        return prog.relations[rule.head.relation].explain == "materialize"
    return bool(witnesses)


def empty_relation(rel, dialect):
    """A declaration-only extension is empty, with typed columns and no implicit grants or NULLs."""
    empty = {"string": "", "integer": "0", "boolean": "false"}
    cols = [f"{lit_sql(empty[c.type], c.type)} AS {q(c.name)}" for c in rel.key]
    # Calcite requires a FROM clause before WHERE. The constant source contributes no facts.
    source = " FROM (VALUES (1)) AS seed(n)" if dialect == "feldera" else ""
    return f"SELECT {', '.join(cols)}{source} WHERE FALSE"


def feldera(prog, witnesses=False, relations=None, inputs=None, tables=True):
    """A Feldera program. `relations` limits the views (a split part); `inputs` are derived or calc relations
    that another part computes: they become input tables here. Without `tables` the base tables are
    left out, because they are already declared (engine/tables.sql of the same pipeline)."""
    relations = prog.derived() if relations is None else [r for r in prog.derived() if r in relations]
    inputs = sorted(inputs or ())
    used = set()
    for name in relations:
        used |= prog.deps(name)
    stmts = _base_tables(prog, names=None if relations == prog.derived() else used) if tables else []
    stmts += _input_tables(prog, inputs)
    for name in relations:
        rel = prog.relations[name]
        if name in prog.bounds:
            body = unrolled(prog, name)
        else:
            body = "\nUNION\n".join(rule_select(prog, r) for r in prog.rules_for(name)) or empty_relation(rel, "feldera")
            if prog.recursive(name):
                cols = ", ".join(f"{q(c.name)} {SQL_TYPE[c.type]} NOT NULL" for c in rel.key)
                stmts.append(f"DECLARE RECURSIVE VIEW {q(name)} ({cols});")
        stmts.append(f"CREATE MATERIALIZED VIEW {q(name)} AS\n{body};")
        for r in prog.rules_for(name):
            if wants_witness(prog, r, witnesses):
                stmts.append(f"CREATE MATERIALIZED VIEW {q(r.witness_relation)} AS\n{witness_select(prog, r)};")
        stmts += [f"CREATE MATERIALIZED VIEW {q(v)} AS\n{s};" for v, s in checks(prog, name)]
    return feldera_names.render("\n\n".join(stmts) + "\n")


def _input_tables(prog, names):
    out = []
    for name in names:
        rel = prog.relations[name]
        cols = [f"{q(c.name)} {SQL_TYPE[c.type]} NOT NULL" for c in rel.key]
        out.append(f"CREATE TABLE {q(name)} ({', '.join(cols)});")
    return out


def input_tables(prog, names):
    """Derived or calc relations another pipeline computes, as input tables of this one."""
    return feldera_names.render("\n\n".join(_input_tables(prog, sorted(names))) + "\n")


def divides(prog):
    """True if a rule of the program divides: then the DuckDB script defines rezono_quotient first."""
    return any(s.op == "div" for r in prog.rules.values() for s in r.assignments)


def duckdb_tables(prog):
    return _base_tables(prog)


def duckdb_relation(prog, name):
    """Statements that (re)compute one derived relation as a table, from lower ones."""
    rel = prog.relations[name]
    rules = prog.rules_for(name)
    if name in prog.bounds:
        return [f"CREATE OR REPLACE TABLE {q(name)} AS\n{unrolled(prog, name, 'duckdb')};"]
    if not prog.recursive(name):
        body = "\nUNION\n".join(rule_select(prog, r, dialect="duckdb") for r in rules) or empty_relation(rel, "duckdb")
        return [f"CREATE OR REPLACE TABLE {q(name)} AS\n{body};"]
    rec = [r for r in rules if any(b.atom.relation == name for b in r.body)]
    base = [r for r in rules if r not in rec]
    if len(rec) != 1 or sum(b.atom.relation == name for b in rec[0].body) != 1 or not base:
        raise NotImplementedError(f"{name}: the batch backend takes linear recursion with one recursive rule "
                                  "and at least one base rule")
    cte = f"{name}__rec"
    cols = ", ".join(q(c.name) for c in rel.key)
    body = ("\nUNION\n".join(rule_select(prog, r, dialect="duckdb") for r in base) + "\nUNION\n"
            + rule_select(prog, rec[0], rename={name: cte}, dialect="duckdb"))
    return [f"CREATE OR REPLACE TABLE {q(name)} AS\nWITH RECURSIVE {q(cte)}({cols}) AS (\n{body}\n) SELECT * FROM {q(cte)};"]


def duckdb_program(prog, witnesses=False, relations=None):
    """All derived relations in evaluation order, plus witness tables, as one batch script."""
    out = [DUCKDB_MACROS] if divides(prog) else []
    for name in prog.derived():
        if relations is not None and name not in relations:
            continue
        out += duckdb_relation(prog, name)
        out += [f"CREATE OR REPLACE TABLE {q(r.witness_relation)} AS\n{witness_select(prog, r, 'duckdb')};"
                for r in prog.rules_for(name) if wants_witness(prog, r, witnesses)]
        out += [f"CREATE OR REPLACE TABLE {q(v)} AS\n{s};" for v, s in checks(prog, name, "duckdb")]
    return out


def views(prog, name):
    """The engine views one derived relation costs: itself, its materialized witnesses and its checks."""
    return (1 + sum(1 for r in prog.rules_for(name) if wants_witness(prog, r, "materialize"))
            + len(checks(prog, name)))
