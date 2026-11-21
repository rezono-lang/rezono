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
- a condition with compare_as (decisions/ordered-rule-scalars.md): an explicit comparison of the UTF-8
  bytes (`encode` on DuckDB, `CAST(... AS VARBINARY)` on Feldera), of the text or of the validated UTC key;
- recursion (linear, one relation): Feldera DECLARE RECURSIVE VIEW; DuckDB WITH RECURSIVE ... UNION;
- a counter with an explicit bound (rules.Bound): no recursion on either engine. The rule is
  unrolled into one level per time it can fire, and what it would add beyond the bound is the check
  `<relation>__exhausted`: reaching the bound is a red check, never a relation cut off in silence.

Witness relations (contracts/rules.yaml): per rule a view with one column per variable, the same FROM
and WHERE as the rule. It reads the final relations, so it is never part of a recursion.
"""

from dataclasses import replace

from . import calc_sql, feldera_names
from .rules import BOOLEAN, Condition, calc_input_table, const_type, is_var, upper
from .sqltext import literal, q

OPS = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">", "ge": ">=", "add": "+", "sub": "-", "mul": "*", "div": "/"}
SQL_TYPE = {"string": "VARCHAR", "integer": "BIGINT", "rational": "VARCHAR", "boolean": "BOOLEAN"}
# Integer division truncated toward zero, on the absolute values, so it does not depend on how `//` rounds a
# negative operand; HUGEINT, so that abs(-2^63) fits. Only the quotient -2^63 / -1 does not fit a BIGINT.
DUCKDB_MACROS = ("CREATE OR REPLACE MACRO rezono_quotient(a, b) AS CAST(CASE WHEN (a < 0) = (b < 0) "
                 "THEN abs(a::HUGEINT) // abs(b::HUGEINT) ELSE -(abs(a::HUGEINT) // abs(b::HUGEINT)) END AS BIGINT);")


# A UTC instant as the request input spells it: YYYY-MM-DDTHH:mm:ss[.digits]Z, ASCII digits only.
UTC_PATTERN = r"[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9]([.][0-9]+)?Z"
UTC_WHOLE = len("0001-01-01T00:00:00Z")


def utc_valid(x, dialect="duckdb"):
    """TRUE if the text is a UTC instant in years 0001 to 9999 on a Gregorian calendar day."""
    if dialect == "duckdb":
        year, month, day = (f"TRY_CAST(substr({x}, {i}, {n}) AS INTEGER)" for i, n in ((1, 4), (6, 2), (9, 2)))
        leap = f"(({year} % 4 = 0 AND {year} % 100 <> 0) OR {year} % 400 = 0)"
        match = f"regexp_full_match({x}, {literal(UTC_PATTERN)})"
    else:
        year, month, day = (f"SAFE_CAST(SUBSTRING({x}, {i}, {n}) AS INTEGER)" for i, n in ((1, 4), (6, 2), (9, 2)))
        leap = f"((MOD({year}, 4) = 0 AND MOD({year}, 100) <> 0) OR MOD({year}, 400) = 0)"
        match = f"RLIKE({x}, {literal('^' + UTC_PATTERN + '$')})"
    last = (f"CASE {month} WHEN 2 THEN CASE WHEN {leap} THEN 29 ELSE 28 END "
            "WHEN 4 THEN 30 WHEN 6 THEN 30 WHEN 9 THEN 30 WHEN 11 THEN 30 ELSE 31 END")
    return f"COALESCE({match} AND {year} >= 1 AND {day} <= {last}, FALSE)"


def utc_key(x, dialect="duckdb"):
    """The comparison key of a valid UTC instant. Without the terminal Z, trailing zeros of the
    fraction and a fraction that becomes empty; its bytes order the instants exactly."""
    if dialect == "duckdb":
        return (f"CASE WHEN length({x}) > {UTC_WHOLE} THEN rtrim(rtrim(substr({x}, 1, length({x}) - 1), '0'), '.') "
                f"ELSE substr({x}, 1, {UTC_WHOLE - 1}) END")
    return (f"CASE WHEN CHAR_LENGTH({x}) > {UTC_WHOLE} "
            f"THEN TRIM(TRAILING '.' FROM TRIM(TRAILING '0' FROM SUBSTRING({x}, 1, CHAR_LENGTH({x}) - 1))) "
            f"ELSE SUBSTRING({x}, 1, {UTC_WHOLE - 1}) END")


def typed_bytes(expr, dialect="duckdb"):
    return f"encode({expr})" if dialect == "duckdb" else f"CAST({expr} AS VARBINARY)"


def typed_condition(c, left, right, dialect="duckdb"):
    """A condition with compare_as: an explicit comparison of UTF-8 bytes (decisions/ordered-rule-scalars.md)."""
    if c.compare_as == "binary_text":
        return f"{typed_bytes(left, dialect)} {OPS[c.op]} {typed_bytes(right, dialect)}"
    return (f"({utc_valid(left, dialect)} AND {utc_valid(right, dialect)} "
            f"AND {typed_bytes(utc_key(left, dialect), dialect)} {OPS[c.op]} {typed_bytes(utc_key(right, dialect), dialect)})")


def lit_sql(term, typ):
    if typ == "integer":
        return f"CAST({int(term)} AS BIGINT)"
    if typ == "boolean":
        return "TRUE" if BOOLEAN[term] else "FALSE"
    return literal(term)


def _parse_rational(term):
    num_s, _, den_s = term.partition("/")
    return int(num_s), int(den_s or "1")


def _sql_col_names(cols):
    out = []
    for c in cols:
        if c.type == "rational":
            out.extend([c.name + "_n", c.name + "_d"])
        else:
            out.append(c.name)
    return out


def _state_bearing_aggregate(prog, rule, agg):
    """When a functional rule aggregates over a relation with an unconstrained `state` column,
    return `(state_col, reason_col_or_None)` so strict Appendix A.3 four-state propagation applies."""
    if prog.relations[rule.head.relation].role != "functional":
        return None
    rel = prog.relations[agg.atom.relation]
    state_col = next(
        (c for t, c in zip(agg.atom.terms, rel.row_columns)
         if c.name == "state" and c.type == "string" and t == "_"),
        None,
    )
    if state_col is None:
        return None
    reason_col = next(
        (c for t, c in zip(agg.atom.terms, rel.row_columns)
         if c.name == "reason" and c.type == "string" and t == "_"),
        None,
    )
    return state_col, reason_col


def has_rational(prog, relations=None):
    """True if any selected relation or its dependencies declares a rational column."""
    names = set(prog.relations) if relations is None else set(relations)
    if relations is not None:
        for n in list(names):
            if n in prog.relations:
                names |= prog.deps(n)
    for n in names:
        rel = prog.relations.get(n)
        if rel is None:
            continue
        cols = rel.key + rel.values + ((rel.value,) if rel.value else ())
        if any(c.type == "rational" for c in cols):
            return True
    return False


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
        self.agg_states = []
        for i, b in enumerate(x for x in rule.body if x.polarity == "positive"):
            rel = prog.relations[b.atom.relation]
            alias = f"t{i}"
            on = []
            self._match(b.atom.terms, rel.row_columns, alias, on)
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
                # Year 0000 is no day either, as for the checker (Python's calendar starts at year 1): with
                # this spelling, a text at or after '0001' has a year Y >= 1.
                text = f"CAST({self.term(s.left, 'string')} AS VARCHAR)"
                cast, match = ("TRY_CAST", "regexp_matches") if dialect == "duckdb" else ("SAFE_CAST", "RLIKE")
                left = (f"CASE WHEN {match}({text}, '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$') AND {text} >= '0001' "
                        f"THEN {cast}({text} AS DATE) END")
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
                self.where.append(typed_condition(c, self.term(c.left, "string"), self.term(c.right, "string"), dialect))
                continue
            t = self.types.get(c.left) or self.types.get(c.right) or const_type(c.left)
            if t == "rational":
                ln, ld = self.rat_term(c.left)
                rn, rd = self.rat_term(c.right)
                self.where.append(f"rezono_cmp({ln}, {ld}, {rn}, {rd}) {OPS[c.op]} 0")
            else:
                self.where.append(f"{self.term(c.left, t)} {OPS[c.op]} {self.term(c.right, t)}")
        for i, b in enumerate(x for x in rule.body if x.polarity == "negative"):
            rel = prog.relations[b.atom.relation]
            alias = f"n{i}"
            conds = []
            for t, col in zip(b.atom.terms, rel.row_columns):
                if col.type == "rational":
                    tn, td = self.rat_term(t)
                    conds.append(f"{alias}.{q(col.name + '_n')} = {tn}")
                    conds.append(f"{alias}.{q(col.name + '_d')} = {td}")
                else:
                    conds.append(f"{alias}.{q(col.name)} = {self.term(t, col.type)}")
            self.frm.append(f"LEFT JOIN {q(rename.get(rel.name, rel.name))} AS {alias} ON {' AND '.join(conds) or 'TRUE'}")
            first_col = rel.key[0]
            first_sql = q(first_col.name + "_n") if first_col.type == "rational" else q(first_col.name)
            self.where.append(f"{alias}.{first_sql} IS NULL")

    def _match(self, terms, cols, alias, where):
        for t, col in zip(terms, cols):
            if col.type == "rational":
                n_expr = f"{alias}.{q(col.name + '_n')}"
                d_expr = f"{alias}.{q(col.name + '_d')}"
                if is_var(t):
                    if t in self.env:
                        en, ed = self.env[t]
                        where.append(f"{n_expr} = {en}")
                        where.append(f"{d_expr} = {ed}")
                    else:
                        self.env[t], self.types[t] = (n_expr, d_expr), "rational"
                else:
                    rn, rd = _parse_rational(t)
                    where.append(f"{n_expr} = CAST({rn} AS BIGINT)")
                    where.append(f"{d_expr} = CAST({rd} AS BIGINT)")
                continue
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
        for t, col in zip(a.atom.terms, rel.row_columns):
            if is_var(t):
                keys.append((t, col))
            elif t != "_":
                if col.type == "rational":
                    rn, rd = _parse_rational(t)
                    filters.append(f"{q(col.name + '_n')} = CAST({rn} AS BIGINT)")
                    filters.append(f"{q(col.name + '_d')} = CAST({rd} AS BIGINT)")
                else:
                    filters.append(f"{q(col.name)} = {lit_sql(t, col.type)}")
        fn = "COUNT(*)" if a.function == "count" else f"{a.function.upper()}({q(a.over)})"
        sel, group_cols, on_parts = [], [], []
        for j, (t, col) in enumerate(keys):
            if col.type == "rational":
                sel.append(f"{q(col.name + '_n')} AS k{j}_n")
                sel.append(f"{q(col.name + '_d')} AS k{j}_d")
                group_cols.extend([q(col.name + "_n"), q(col.name + "_d")])
                en, ed = self.env[t]
                on_parts.append(f"{alias}.k{j}_n = {en}")
                on_parts.append(f"{alias}.k{j}_d = {ed}")
            else:
                sel.append(f"{q(col.name)} AS k{j}")
                group_cols.append(q(col.name))
                on_parts.append(f"{alias}.k{j} = {self.env[t]}")
        state_info = _state_bearing_aggregate(self.prog, self.rule, a)
        sel.append(f"CAST({fn} AS BIGINT) AS r")
        if state_info is not None:
            state_col, reason_col = state_info
            st_q = q(state_col.name)
            rsn_col = q(reason_col.name) if reason_col is not None else "CAST('' AS VARCHAR)"
            sel.extend([
                "CAST(COUNT(*) AS BIGINT) AS cnt",
                (f"CAST(MAX(CASE {st_q} WHEN 'invalid' THEN 3 WHEN 'unknown' THEN 2 "
                 f"WHEN 'not_applicable' THEN 1 ELSE 0 END) AS BIGINT) AS st"),
                f"MIN(CASE WHEN {st_q} = 'invalid' THEN {rsn_col} END) AS rsn_inv",
                f"MIN(CASE WHEN {st_q} = 'unknown' THEN {rsn_col} END) AS rsn_unk",
                f"MIN(CASE WHEN {st_q} = 'not_applicable' THEN {rsn_col} END) AS rsn_na",
            ])
        sub = f"SELECT {', '.join(sel)} FROM {q(rel.name)}"
        if filters:
            sub += " WHERE " + " AND ".join(filters)
        if group_cols:
            sub += " GROUP BY " + ", ".join(group_cols)
        elif a.function in ("min", "max") and state_info is None:
            sub += " HAVING COUNT(*) > 0"   # a global min or max over nothing has no conclusion, not NULL
        on = " AND ".join(on_parts) or "TRUE"
        if state_info is not None:
            if not self.frm:
                self.frm.append(f"({sub}) AS {alias}")
            else:
                self.frm.append(f"LEFT JOIN ({sub}) AS {alias} ON {on}")
            self.env[a.var] = f"COALESCE({alias}.r, CAST(0 AS BIGINT))"
            if a.function in ("count", "sum"):
                st_code = f"COALESCE({alias}.st, CAST(0 AS BIGINT))"
                rsn = (f"CAST(CASE COALESCE({alias}.st, CAST(0 AS BIGINT)) "
                       f"WHEN 3 THEN COALESCE({alias}.rsn_inv, 'invalid') "
                       f"WHEN 2 THEN COALESCE({alias}.rsn_unk, 'no_value') "
                       f"WHEN 1 THEN COALESCE({alias}.rsn_na, 'empty') "
                       f"ELSE '' END AS VARCHAR)")
            else:
                st_code = (f"CASE WHEN {alias}.cnt IS NULL OR {alias}.cnt = 0 THEN CAST(1 AS BIGINT) "
                           f"ELSE COALESCE({alias}.st, CAST(0 AS BIGINT)) END")
                rsn = (f"CAST(CASE WHEN {alias}.cnt IS NULL OR {alias}.cnt = 0 THEN 'empty' "
                       f"WHEN {alias}.st = 3 THEN COALESCE({alias}.rsn_inv, 'invalid') "
                       f"WHEN {alias}.st = 2 THEN COALESCE({alias}.rsn_unk, 'no_value') "
                       f"WHEN {alias}.st = 1 THEN COALESCE({alias}.rsn_na, 'empty') "
                       f"ELSE '' END AS VARCHAR)")
            self.agg_states.append((st_code, rsn))
        elif not self.frm:
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

    def rat_term(self, t):
        if is_var(t):
            return self.env[t]
        rn, rd = _parse_rational(t)
        return f"CAST({rn} AS BIGINT)", f"CAST({rd} AS BIGINT)"

    def from_where(self):
        return f"FROM {' '.join(self.frm)}" + (" WHERE " + " AND ".join(self.where) if self.where else "")

    def select(self, exprs_names):
        return f"SELECT DISTINCT {', '.join(f'{e} AS {q(n)}' for e, n in exprs_names)} {self.from_where()}"


def rule_select(prog, rule, rename=None, dialect="feldera"):
    rel = prog.relations[rule.head.relation]
    r = RuleSQL(prog, rule, rename, dialect)
    cols = []
    for t, c in zip(rule.head.terms, rel.key):
        if c.type == "rational":
            tn, td = r.rat_term(t)
            cols.append((tn, c.name + "_n"))
            cols.append((td, c.name + "_d"))
        else:
            cols.append((r.term(t, c.type), c.name))
    return r.select(cols)


def functional_candidate_select(prog, rule, dialect="feldera"):
    """One rule of a `role: functional` relation as candidate rows `(k..., __st, __rsn, __v)`
    (or `(__vn, __vd)` for rational values)."""
    rel = prog.relations[rule.head.relation]
    r = RuleSQL(prog, rule, dialect=dialect)
    cols = []
    for j, (t, c) in enumerate(zip(rule.head.terms[:-1], rel.key)):
        if c.type == "rational":
            tn, td = r.rat_term(t)
            cols.append((tn, f"k{j}_n"))
            cols.append((td, f"k{j}_d"))
        else:
            expr = r.term(t, c.type)
            if c.type == "string":
                expr = f"CAST({expr} AS VARCHAR)"
            cols.append((expr, f"k{j}"))
    if not r.agg_states:
        st_expr, rsn_expr = "CAST(0 AS BIGINT)", "CAST('' AS VARCHAR)"
    elif len(r.agg_states) == 1:
        st_expr, rsn_expr = r.agg_states[0]
    else:
        worst = f"GREATEST({', '.join(s for s, _ in r.agg_states)})"
        st_expr = f"CAST({worst} AS BIGINT)"
        rsn_expr = ("CAST(CASE "
                    + " ".join(f"WHEN {s} = {worst} THEN {rs}" for s, rs in r.agg_states)
                    + " ELSE '' END AS VARCHAR)")
    cols.append((st_expr, "__st"))
    cols.append((rsn_expr, "__rsn"))
    vt, vc = rule.head.terms[-1], rel.value
    if vc.type == "rational":
        vn, vd = r.rat_term(vt)
        cols.append((f"rezono_add_n({vn}, {vd}, CAST(0 AS BIGINT), CAST(1 AS BIGINT))", "__vn"))
        cols.append((f"rezono_add_d({vn}, {vd}, CAST(0 AS BIGINT), CAST(1 AS BIGINT))", "__vd"))
    elif vc.type == "string":
        cols.append((f"CAST({r.term(vt, 'string')} AS VARCHAR)", "__v"))
    elif vc.type == "integer":
        cols.append((f"CAST({r.term(vt, 'integer')} AS BIGINT)", "__v"))
    else:
        cols.append((r.term(vt, "boolean"), "__v"))
    return r.select(cols)


def functional_select(prog, name, dialect="feldera"):
    """One co-located NOT NULL `(key..., state, reason, value)` query for a `role: functional` relation,
    LEFT JOINed over its declared closed domain (decisions/language-rezono-1.md, sections 2, 4 and 5.4)."""
    rel = prog.relations[name]
    dom = prog.relations[rel.domain]
    cand_sql = "\nUNION\n".join(functional_candidate_select(prog, r, dialect) for r in prog.rules_for(name))
    key_specs = []
    for j, (c, dc) in enumerate(zip(rel.key, dom.key)):
        if c.type == "rational":
            key_specs.append((f"k{j}_n", dc.name + "_n", c.name + "_n"))
            key_specs.append((f"k{j}_d", dc.name + "_d", c.name + "_d"))
        else:
            key_specs.append((f"k{j}", dc.name, c.name))
    agg_cols = [q(ck) for ck, _, _ in key_specs] + [
        'CAST(COUNT(*) AS BIGINT) AS "__cnt"',
        'CAST(MAX("__st") AS BIGINT) AS "__max_st"',
        'CAST(SUM(CASE WHEN "__st" = 0 THEN 1 ELSE 0 END) AS BIGINT) AS "__known_cnt"',
        'MIN(CASE WHEN "__st" = 3 THEN "__rsn" END) AS "__rsn_inv"',
        'MIN(CASE WHEN "__st" = 2 THEN "__rsn" END) AS "__rsn_unk"',
        'MIN(CASE WHEN "__st" = 1 THEN "__rsn" END) AS "__rsn_na"',
    ]
    vtype = rel.value.type
    if vtype == "rational":
        agg_cols += [
            'MIN(CASE WHEN "__st" = 0 THEN "__vn" END) AS "__min_vn"',
            'MAX(CASE WHEN "__st" = 0 THEN "__vn" END) AS "__max_vn"',
            'MIN(CASE WHEN "__st" = 0 THEN "__vd" END) AS "__min_vd"',
            'MAX(CASE WHEN "__st" = 0 THEN "__vd" END) AS "__max_vd"',
        ]
    elif vtype == "boolean":
        agg_cols += [
            'MIN(CASE WHEN "__st" = 0 THEN CASE WHEN "__v" THEN 1 ELSE 0 END END) AS "__min_v"',
            'MAX(CASE WHEN "__st" = 0 THEN CASE WHEN "__v" THEN 1 ELSE 0 END END) AS "__max_v"',
        ]
    else:
        agg_cols += [
            'MIN(CASE WHEN "__st" = 0 THEN "__v" END) AS "__min_v"',
            'MAX(CASE WHEN "__st" = 0 THEN "__v" END) AS "__max_v"',
        ]
    group_by = ", ".join(q(ck) for ck, _, _ in key_specs)
    agg_sql = f'SELECT {", ".join(agg_cols)} FROM "__cand" GROUP BY {group_by}'

    empty_state = rel.empty_state or "unknown"
    empty_reason = rel.empty_reason or ("empty" if empty_state == "not_applicable" else "no_value")
    if vtype == "rational":
        conflict = '(g."__known_cnt" > 0 AND (g."__min_vn" <> g."__max_vn" OR g."__min_vd" <> g."__max_vd"))'
        is_known = ('(g."__cnt" IS NOT NULL AND g."__max_st" = 0 AND g."__known_cnt" > 0 '
                    'AND g."__min_vn" = g."__max_vn" AND g."__min_vd" = g."__max_vd" AND g."__min_vd" > 0)')
        val_selects = [
            (f'CAST(CASE WHEN {is_known} THEN COALESCE(g."__min_vn", CAST(0 AS BIGINT)) '
             f'ELSE CAST(0 AS BIGINT) END AS BIGINT) AS {q(rel.value.name + "_n")}'),
            (f'CAST(CASE WHEN {is_known} THEN COALESCE(g."__min_vd", CAST(1 AS BIGINT)) '
             f'ELSE CAST(1 AS BIGINT) END AS BIGINT) AS {q(rel.value.name + "_d")}'),
        ]
    else:
        conflict = '(g."__known_cnt" > 0 AND g."__min_v" <> g."__max_v")'
        is_known = '(g."__cnt" IS NOT NULL AND g."__max_st" = 0 AND g."__known_cnt" > 0 AND g."__min_v" = g."__max_v")'
        if vtype == "string":
            val_selects = [
                f"CAST(CASE WHEN {is_known} THEN COALESCE(g.\"__min_v\", '') ELSE '' END AS VARCHAR) AS {q(rel.value.name)}"
            ]
        elif vtype == "integer":
            val_selects = [
                (f'CAST(CASE WHEN {is_known} THEN COALESCE(g."__min_v", CAST(0 AS BIGINT)) '
                 f'ELSE CAST(0 AS BIGINT) END AS BIGINT) AS {q(rel.value.name)}')
            ]
        else:
            val_selects = [
                f'CASE WHEN {is_known} THEN (COALESCE(g."__min_v", 0) = 1) ELSE FALSE END AS {q(rel.value.name)}'
            ]

    state_expr = (
        f'CAST(CASE WHEN g."__cnt" IS NULL THEN {literal(empty_state)} '
        f'WHEN g."__max_st" = 3 THEN \'invalid\' '
        f'WHEN {conflict} THEN \'invalid\' '
        f'WHEN g."__max_st" = 2 THEN \'unknown\' '
        f'WHEN g."__max_st" = 1 THEN \'not_applicable\' '
        f'ELSE \'known\' END AS VARCHAR) AS "state"'
    )
    reason_expr = (
        f'CAST(CASE WHEN g."__cnt" IS NULL THEN {literal(empty_reason)} '
        f'WHEN g."__max_st" = 3 THEN COALESCE(g."__rsn_inv", \'invalid\') '
        f'WHEN {conflict} THEN \'multiple_values\' '
        f'WHEN g."__max_st" = 2 THEN COALESCE(g."__rsn_unk", \'no_value\') '
        f'WHEN g."__max_st" = 1 THEN COALESCE(g."__rsn_na", \'empty\') '
        f'ELSE \'\' END AS VARCHAR) AS "reason"'
    )
    dom_cols = ", ".join(q(dk) for _, dk, _ in key_specs)
    out_keys = [f"d.{q(dk)} AS {q(ok)}" for _, dk, ok in key_specs]
    join_on = " AND ".join(f"g.{q(ck)} = d.{q(dk)}" for ck, dk, _ in key_specs)
    dom_source = relation_source(dom) if dialect == "duckdb" else dom.name
    return (
        f'WITH "__cand" AS (\n{cand_sql}\n),\n'
        f'"__agg" AS (\n{agg_sql}\n)\n'
        f"SELECT {', '.join(out_keys + [state_expr, reason_expr] + val_selects)}\n"
        f"FROM (SELECT DISTINCT {dom_cols} FROM {q(dom_source)}) AS d\n"
        f'LEFT JOIN "__agg" AS g ON {join_on}'
    )


def witness_select(prog, rule, dialect="feldera"):
    r = RuleSQL(prog, rule, dialect=dialect)
    if not rule.variables:
        return r.select([("TRUE", EMPTY_SUBSTITUTION)])
    cols = []
    for v in rule.variables:
        if r.types[v] == "rational":
            vn, vd = r.rat_term(v)
            cols.append((vn, var_col(v) + "_n"))
            cols.append((vd, var_col(v) + "_d"))
        else:
            cols.append((r.term(v, r.types[v]), var_col(v)))
    return r.select(cols)


def _col_defs(cols):
    out = []
    for c in cols:
        if c.type == "rational":
            out.append(f"{q(c.name + '_n')} BIGINT NOT NULL")
            out.append(f"{q(c.name + '_d')} BIGINT NOT NULL")
        else:
            out.append(f"{q(c.name)} {SQL_TYPE[c.type]} NOT NULL")
    return out


def _base_tables(prog, names=None):
    out = []
    for rel in prog.relations.values():
        if rel.role != "base" or (names is not None and rel.name not in names):
            continue
        cols = _col_defs(rel.key + rel.values)
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


def functional_checks(prog, name):
    """For a functional derivation with conflict_policy == 'block', one check view `<name>__invalid`
    holding any domain key whose state is 'invalid'. A row in it blocks publication."""
    rel = prog.relations[name]
    if rel.role != "functional" or rel.conflict_policy != "block":
        return []
    cols = ", ".join(q(c) for c in _sql_col_names(rel.key))
    return [(f"{name}__invalid", f"SELECT {cols} FROM {q(name)} WHERE {q('state')} = 'invalid'")]


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
    """Every check view of one derived or functional relation, as (view, SELECT): a row in any of them is a red check."""
    return outcome_checks(prog, name) + functional_checks(prog, name) + bound_checks(prog, name, dialect)


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
    cols = []
    for c in rel.key:
        if c.type == "rational":
            cols.append(f"CAST(0 AS BIGINT) AS {q(c.name + '_n')}")
            cols.append(f"CAST(1 AS BIGINT) AS {q(c.name + '_d')}")
        else:
            cols.append(f"{lit_sql(empty[c.type], c.type)} AS {q(c.name)}")
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
    stmts = []
    if has_rational(prog, relations):
        stmts.append(calc_sql.feldera_functions().strip())
    if tables:
        stmts += _base_tables(prog, names=None if relations == prog.derived() else used)
    stmts += _input_tables(prog, inputs)
    for name in relations:
        rel = prog.relations[name]
        if rel.role == "functional":
            body = functional_select(prog, name, dialect="feldera")
        elif name in prog.bounds:
            body = unrolled(prog, name)
        else:
            body = "\nUNION\n".join(rule_select(prog, r) for r in prog.rules_for(name)) or empty_relation(rel, "feldera")
            if prog.recursive(name):
                cols = ", ".join(_col_defs(rel.key))
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
        cols = _col_defs(rel.row_columns)
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
    """Statements that (re)compute one derived or functional relation as a table, from lower ones."""
    rel = prog.relations[name]
    if rel.role == "functional":
        return [f"CREATE OR REPLACE TABLE {q(name)} AS\n{functional_select(prog, name, dialect='duckdb')};"]
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
    cols = ", ".join(q(c) for c in _sql_col_names(rel.key))
    body = ("\nUNION\n".join(rule_select(prog, r, dialect="duckdb") for r in base) + "\nUNION\n"
            + rule_select(prog, rec[0], rename={name: cte}, dialect="duckdb"))
    return [f"CREATE OR REPLACE TABLE {q(name)} AS\nWITH RECURSIVE {q(cte)}({cols}) AS (\n{body}\n) SELECT * FROM {q(cte)};"]


def duckdb_program(prog, witnesses=False, relations=None):
    """All derived relations in evaluation order, plus witness tables, as one batch script."""
    out = [DUCKDB_MACROS] if divides(prog) else []
    if has_rational(prog, relations):
        out.append(calc_sql.DUCKDB_MACROS)
    for name in prog.derived():
        if relations is not None and name not in relations:
            continue
        out += duckdb_relation(prog, name)
        out += [f"CREATE OR REPLACE TABLE {q(r.witness_relation)} AS\n{witness_select(prog, r, 'duckdb')};"
                for r in prog.rules_for(name) if wants_witness(prog, r, witnesses)]
        out += [f"CREATE OR REPLACE TABLE {q(v)} AS\n{s};" for v, s in checks(prog, name, "duckdb")]
    return out


def is_functional_aggregate(prog, name):
    """True when a functional derivation needs candidate aggregation, precedence, or rational arithmetic
    (more than one rule, any aggregate, or a rational column), else a deterministic projection."""
    rel = prog.relations[name]
    if rel.role != "functional":
        return False
    rules = prog.rules_for(name)
    return (
        len(rules) > 1
        or rel.value.type == "rational"
        or any(c.type == "rational" for c in rel.key)
        or any(r.aggregates for r in rules)
    )


def views(prog, name):
    """The engine view budget cost of one derived or functional relation: itself (weight 1 for derived
    or deterministic functional projection, weight 2 for candidate-aggregating / precedence / rational
    functional derivation), its materialized witnesses, and its checks."""
    base = 2 if is_functional_aggregate(prog, name) else 1
    return (base + sum(1 for r in prog.rules_for(name) if wants_witness(prog, r, "materialize"))
            + len(checks(prog, name)))
