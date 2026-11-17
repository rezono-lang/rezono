# --- No new violations ------------------------------------------------------------------------------------------

from __future__ import annotations

import json
from collections import Counter

from .. import scenarios
from .. import pack as packs
from ..pack import ACCESS

from .spec import OperationError
from .maps import Maps
from .state import text_of


def violations(p: packs.Pack, rows: dict[str, list[tuple]]) -> Counter:
    """Every violation of the pack's checks on one state, as (check, kind, subject, path, row), counted: the
    integrity views of the compiled pack on DuckDB."""
    try:
        import duckdb
    except ImportError as e:  # the batch extra of rezono-compiler
        raise OperationError("this operation checks for new violations on DuckDB; install rezono-compiler[batch]") from e
    from .. import emit
    files = emit.compile_pack(p)
    checks = json.loads(files["bundle/schema-bundle.json"])["checks"]
    if not checks:  # then integrity.sql has no view to union
        return Counter()
    db = duckdb.connect()
    try:
        db.execute(emit.DUCKDB_FUNCTIONS)
        for script in (files["engine/tables.sql"],
                       emit.duckdb(files["engine/integrity.sql"])):
            if "CREATE" in script:  # a pack without kinds or checks has an empty script
                db.execute(script)
        params = json.loads(files["engine/parameters.json"])
        tables = {t: [tuple(r.values()) for r in rs] for t, rs in params.items()} | rows
        for table, rs in tables.items():
            if rs:
                db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
        # one view per check kind; validation_result names the logical check in `info`
        by_name = {c["view"]: c for c in checks}
        out: Counter = Counter()
        for info, subject, value in db.execute("SELECT info, subject, value FROM validation_result").fetchall():
            c = by_name[info]
            row = (subject,) if value == "" else (subject, value)
            out[(c["check"], c["kind"], c.get("subject"), c.get("path"), row)] += 1
        return out
    finally:
        db.close()


def new_violations(p: packs.Pack, before: Counter, after: Counter, mp: Maps, ids: dict,
                   checks: dict | None = None) -> list:
    """Violations after that are not the image of a violation before. The path only shows the check: kind and
    subject name it. The kind maps as a kind and the subject within its kind (a slot keeps its name unless the
    operation renames that slot); `checks` maps a check that moved, (kind, subject) -> (kind, subject), such as
    a class rule that went to a subkind. Of a row only the columns that hold an element id map through `ids`:
    the first, and the value of a reference or of an identifier."""
    image: Counter = Counter()
    for (c, k, s, _, r), n in before.items():
        kind = p.kinds.get(k)
        id_value = kind is not None and (s == kind.identifier or (s in kind.slots and kind.slots[s].arrow))
        r = tuple(ids.get(v, v) if i == 0 or (i == 1 and id_value) else v for i, v in enumerate(r))
        k2, s2 = (checks or {}).get((k, s), (mp.kinds.get(k, k), mp.keys.get((k, s), s)))
        image[(c, k2, s2, r)] += n
    return sorted((Counter({(c, k, s, r): n for (c, k, s, _, r), n in after.items()}) - image).elements(), key=repr)


def guarded(p: packs.Pack, rows: dict[str, list[tuple]]) -> set[tuple[str, tuple]]:
    """What the pack's rules give on one state that must not grow: the rows of every access relation, of
    every invariant, and of every outcome check, as (relation, row of canonical text), on DuckDB."""
    if not p.rules:
        return set()
    from .. import batch, rules as ir, rules_sql
    prog = ir.load(p.rules)
    if prog.calc_inputs():
        raise OperationError("rules: checking schema operations with calculation inputs requires checked phase execution")
    con = batch.connect(prog, scenarios.rule_rows(p, prog, rows))
    try:
        batch.compute(con, prog)
        names = [n for n, r in prog.relations.items() if r.role == "derived" and (n in ACCESS or r.invariant)]
        out = {(n, r) for n, rs in (batch.read(con, prog, names) if names else {}).items() for r in rs}
        for n in sorted(prog.relations):
            for view, select in rules_sql.checks(prog, n, "duckdb"):
                out |= {(view, tuple(map(text_of, r))) for r in con.execute(select).fetchall()}
        return out
    finally:
        con.close()


def grown(before: set, after: set, mp: Maps, access: dict[str, int | None]) -> tuple[list, list]:
    """(access rows, invariant and outcome rows) after that are not the image of a row before. Only the kind
    column of an access relation maps: rule_edits blocks every other constant and every head that carries
    an id the operation changes, so nothing else in these rows can change name."""
    image = set()
    for n, r in before:
        c = access.get(n)
        image.add((n, tuple(mp.kinds.get(v, v) if i == c else v for i, v in enumerate(r))))
    new = sorted(after - image)
    return [x for x in new if x[0] in ACCESS], [x for x in new if x[0] not in ACCESS]
