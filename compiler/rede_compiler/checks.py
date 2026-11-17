"""Integrity checks as data (decision E11, docs/compiler.md#design-checks-as-data-e11).

One materialised view per check kind instead of one per slot. Which slot has which check is a row of a
metadata table `rede__<facet>` (in engine/parameters.json, loaded like the parameters), and the generic views
read every element and every slot value through local relations. The SQL depends only on which tables exist,
never on a facet, so a schema change of a check is a change of rows. Pattern, unique key, path equation and
class rule keep their own SQL per check, as branches of one view per check kind.

`validation_result` is the same row for row as with one view per check: `info` names the logical check
(`<kind>__<subject>__<check>`), which is no longer an engine view.
"""

from __future__ import annotations

from .pack import Pack
from .sqltext import literal, q

P = "rede__"
RESERVED = "rede"
# The metadata tables: (facet, columns), every column VARCHAR except the BIGINT ones.
META = (("is_a", ("kind", "parent")), ("required", ("kind", "slot")), ("single", ("kind", "slot")),
        ("arrow", ("kind", "slot", "target")), ("enum", ("kind", "slot", "enumeration")),
        ("minimum", ("kind", "slot", "v")), ("maximum", ("kind", "slot", "v")), ("constant", ("kind", "slot", "v")),
        ("minimum_cardinality", ("kind", "slot", "v")), ("maximum_cardinality", ("kind", "slot", "v")))
BIGINT = {"minimum", "maximum", "minimum_cardinality", "maximum_cardinality"}
LOCAL = ("element", "value", "integer", "enum_value")
GENERIC = ("identification", "reference", "totality", "functionality", "value_range", "cardinality")
PER_CHECK = ("pattern", "unique", "path_equation", "rule")
ORDER = GENERIC + PER_CHECK


def lit(v) -> str:
    return f"CAST({literal(v)} AS VARCHAR)"


def text(sql: str) -> str:
    return f"CAST({sql} AS VARCHAR)"


def names(pack: Pack) -> list[str]:
    """Every engine name this module makes, for the namespace check."""
    return [P + f for f, _ in META] + [P + n for n in LOCAL] + [P + c for c in ORDER]


def tables() -> str:
    """The metadata tables. They always exist, also without rows, so the first required slot is a row too."""
    out = ["\n-- Check metadata (decision E11): which slot has which check, as rows (engine/parameters.json).\n"]
    for facet, cols in META:
        types = ", ".join(f"{c} {'BIGINT' if c == 'v' and facet in BIGINT else 'VARCHAR'} NOT NULL" for c in cols)
        out.append(f"CREATE TABLE {q(P + facet)} ({types});\n")
    return "".join(out)


def rows(pack: Pack) -> dict[str, list[dict]]:
    """The metadata rows, from the compiled definition only (never from facts, deltas or scenarios)."""
    out: dict[str, list[dict]] = {P + f: [] for f, _ in META}
    for k, kind in pack.kinds.items():
        if kind.parent:
            out[P + "is_a"].append({"kind": k, "parent": kind.parent})
        for s in kind.slots.values():
            key = {"kind": k, "slot": s.name}
            if s.required:
                out[P + "required"].append(key)
            if not s.multivalued:
                out[P + "single"].append(key)
            if s.arrow:
                out[P + "arrow"].append(key | {"target": s.range})
            if s.enum:
                out[P + "enum"].append(key | {"enumeration": s.enum})
            for facet in ("minimum", "maximum", "minimum_cardinality", "maximum_cardinality"):
                if getattr(s, facet) is not None:
                    out[P + facet].append(key | {"v": getattr(s, facet)})
            if s.constant is not None:
                out[P + "constant"].append(key | {"v": str(s.constant)})
    return {t: sorted(r, key=lambda d: tuple(str(v) for v in d.values())) for t, r in out.items()}


def local(pack: Pack) -> tuple[str, set[str]]:
    """The local relations over every element and slot value, and which of them have branches. They depend
    only on which tables exist; a relation without branches (a pack without enums) is left out."""
    slots = [s for kind in pack.kinds.values() for s in kind.slots.values()]
    rel = {
        "element": [f"SELECT {lit(k)} AS kind, {text('id')} AS id FROM {q(k)}" for k in pack.kinds],
        "value": [f"SELECT {lit(s.kind)} AS kind, {lit(s.name)} AS slot, {text('id')} AS id, {text('v')} AS v "
                  f"FROM {q(s.table)}" for s in slots],
        "integer": [f"SELECT {lit(s.kind)} AS kind, {lit(s.name)} AS slot, {text('id')} AS id, v FROM {q(s.table)}"
                    for s in slots if s.sql_type == "BIGINT"],
        "enum_value": [f"SELECT {lit(e)} AS enumeration, id FROM {q(e)}" for e in pack.enums],
    }
    sql = "".join(f"\nCREATE LOCAL VIEW {q(P + n)} AS\n" + "\nUNION ALL\n".join(parts) + ";\n"
                  for n, parts in rel.items() if parts)
    return sql, {n for n, parts in rel.items() if parts}


def wrap(parts: list[str], op: str) -> str:
    """Set operations of parts, each in its own subquery so that no precedence rule decides."""
    return f"\n{op}\n".join(f"SELECT * FROM (\n{p}\n) r{i}" for i, p in enumerate(parts, 1))


def generic(check: str, have: set[str]) -> str:
    """The query of one generic check kind, with the columns (kind, slot, path, id, value) as text."""
    E, V, I = q(P + "element"), q(P + "value"), q(P + "integer")
    on = "m.kind = x.kind AND m.slot = x.slot"
    row = "x.kind, x.slot, x.slot, x.id, x.v"
    head = "SELECT x.kind AS kind, x.slot AS slot, x.slot AS path, x.id AS id, x.v AS value"
    empty = "CAST('' AS VARCHAR)"
    if check == "identification":
        return (f"SELECT kind, {empty} AS slot, {empty} AS path, id, {text('COUNT(*)')} AS value "
                f"FROM {E} GROUP BY kind, id HAVING COUNT(*) > 1")
    if check == "reference":
        is_a = lit("is_a")
        parts = [f"SELECT m.kind AS kind, {is_a} AS slot, {is_a} AS path, e.id AS id, {empty} AS value "
                 f"FROM {q(P + 'is_a')} m JOIN {E} e ON e.kind = m.kind\n"
                 f"EXCEPT SELECT m.kind, {is_a}, {is_a}, p.id, {empty} FROM {q(P + 'is_a')} m "
                 f"JOIN {E} p ON p.kind = m.parent"]
        if "value" in have:
            parts.append(f"{head} FROM {V} x\nEXCEPT SELECT {row} FROM {V} x JOIN {E} e ON e.kind = x.kind AND e.id = x.id")
            parts.append(f"{head} FROM {V} x JOIN {q(P + 'arrow')} m ON {on}\n"
                         f"EXCEPT SELECT {row} FROM {V} x JOIN {q(P + 'arrow')} m ON {on} "
                         f"JOIN {E} t ON t.kind = m.target AND t.id = x.v")
        return wrap(parts, "UNION")
    if check == "totality":
        return (f"SELECT m.kind AS kind, m.slot AS slot, m.slot AS path, e.id AS id, {empty} AS value "
                f"FROM {q(P + 'required')} m JOIN {E} e ON e.kind = m.kind\n"
                f"EXCEPT SELECT kind, slot, slot, id, {empty} FROM {V}")
    if check == "functionality":
        return (f"SELECT x.kind AS kind, x.slot AS slot, x.slot AS path, x.id AS id, "
                f"{text('COUNT(DISTINCT x.v)')} AS value FROM {V} x JOIN {q(P + 'single')} m ON {on}\n"
                f"GROUP BY x.kind, x.slot, x.id HAVING COUNT(DISTINCT x.v) > 1")
    if check == "value_range":
        cols = "x.kind, x.slot, x.id, x.v"
        parts = []
        if "enum_value" in have:
            m = f"{V} x JOIN {q(P + 'enum')} m ON {on}"
            parts.append(f"SELECT {cols} FROM {m}\nEXCEPT SELECT {cols} FROM {m} JOIN {q(P + 'enum_value')} a "
                         f"ON a.enumeration = m.enumeration AND a.id = x.v")
        if "integer" in have:
            for facet, op in (("minimum", "<"), ("maximum", ">")):
                parts.append(f"SELECT i.kind, i.slot, i.id, {text('i.v')} AS v FROM {I} i "
                             f"JOIN {q(P + facet)} b ON b.kind = i.kind AND b.slot = i.slot WHERE i.v {op} b.v")
        m = f"{V} x JOIN (SELECT DISTINCT kind, slot FROM {q(P + 'constant')}) m ON {on}"
        parts.append(f"SELECT {cols} FROM {m}\nEXCEPT SELECT {cols} FROM {m} JOIN {q(P + 'constant')} c "
                     f"ON c.kind = x.kind AND c.slot = x.slot AND c.v = x.v")
        return (f"SELECT DISTINCT kind, slot, slot AS path, id, v AS value FROM (\n"
                f"{wrap(parts, 'UNION ALL')}\n) y")
    if check == "cardinality":
        limits = (f"SELECT kind, slot FROM {q(P + 'minimum_cardinality')} "
                  f"UNION SELECT kind, slot FROM {q(P + 'maximum_cardinality')}")
        counts = (f"SELECT x.kind AS kind, x.slot AS slot, x.id AS id, COUNT(DISTINCT x.v) AS n FROM {V} x "
                  f"JOIN ({limits}) l ON l.kind = x.kind AND l.slot = x.slot "
                  f"JOIN {E} e ON e.kind = x.kind AND e.id = x.id GROUP BY x.kind, x.slot, x.id\n"
                  f"UNION ALL SELECT kind, slot, id, CAST(0 AS BIGINT) AS n FROM (\n"
                  f"SELECT l.kind AS kind, l.slot AS slot, e.id AS id FROM ({limits}) l JOIN {E} e ON e.kind = l.kind\n"
                  f"EXCEPT SELECT kind, slot, id FROM {V}) z")
        return "\nUNION\n".join(
            f"SELECT c.kind AS kind, c.slot AS slot, c.slot AS path, c.id AS id, {text('c.n')} AS value "
            f"FROM ({counts}) c JOIN {q(P + b)} b ON b.kind = c.kind AND b.slot = c.slot WHERE c.n {op} b.v"
            for b, op in (("minimum_cardinality", "<"), ("maximum_cardinality", ">")))
    raise ValueError(check)


def per_check(checks, check: str) -> str:
    """Today's SQL of each check of one kind, unchanged, as branches of one view."""
    return "\nUNION ALL\n".join(
        f"SELECT {lit(kind)} AS kind, {lit(subject)} AS slot, {lit(path)} AS path, {text('id')} AS id, "
        f"{text(value)} AS value FROM (\n{body}\n) x"
        for _, c, kind, subject, body, path, value in checks if c == check)


def kinds_of(pack: Pack, checks) -> list[str]:
    """The check kinds with a view. The generic ones always exist once there are tables to read (kinds; for
    those over slot values, a slot), so a new required slot or bound is a row; the others when present."""
    if not pack.kinds:
        return []
    slots = any(kind.slots for kind in pack.kinds.values())
    present = {c[1] for c in checks}
    return ([c for c in GENERIC if slots or c in ("identification", "reference")]
            + [c for c in PER_CHECK if c in present])


def views(pack: Pack, checks) -> tuple[str, int]:
    """engine/integrity.sql without the seal: the local relations, one view per check kind and
    validation_result; and the number of views a build makes of it."""
    from .emit import view
    order = kinds_of(pack, checks)
    if not order:
        return "", 0
    sql, have = local(pack)
    out = [sql]
    for check in order:
        out.append(view(P + check, generic(check, have) if check in GENERIC else per_check(checks, check)))
    out.append(view("validation_result", "\nUNION ALL\n".join(
        f"SELECT {lit(c)} AS type, id AS subject, kind AS instantiates, path, value, "
        f"CASE WHEN slot = '' THEN kind || {literal('__' + c)} ELSE kind || '__' || slot || {literal('__' + c)} END "
        f"AS info FROM {q(P + c)}" for c in order)))
    return "".join(out), len(have) + len(order) + 1


def relation(check: str) -> str:
    """The engine view that holds the rows of a logical check of this kind."""
    return P + check
