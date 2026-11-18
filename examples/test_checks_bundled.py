"""The bundled checks (one view per check kind) on every example pack and fact state.

For every example pack and every fact state (the facts, each scenario, each diagnostic), and for each state
again with planted violations of every generic check made from the IR, the compiled `engine/integrity.sql`
runs on DuckDB: `validation_result` has no duplicate row, a pack with diagnostics shows violations, and every
generic check finds rows somewhere. That the rows are the right ones is the independent reference's to say
(`genpack.reference()`, compiler/tests/test_generality.py); until E11's step 4 this file also compared them
with the per-slot views of before E11, which are removed. DuckDB only, no Feldera.
"""

import datetime
import json
from collections import Counter

import duckdb
import pytest

from rezono_compiler import checks, emit, pack, scenarios
from support import REPO

PACKS = sorted(p.parent for p in (REPO / "examples").glob("**/pack.yaml")
               if (p.parent / "schema").is_dir() and "expected" not in p.parts)
COVERED: Counter = Counter()  # violation rows per generic check, over all packs and states


def run(scripts: list[str], tables: dict[str, list[tuple]]) -> Counter:
    db = duckdb.connect()
    try:
        db.execute(emit.DUCKDB_FUNCTIONS)
        for s in scripts:
            if "CREATE" in s:
                db.execute(emit.duckdb(s))
        for table, rs in tables.items():
            if rs:
                db.executemany(f"INSERT INTO {emit.q(table)} VALUES ({', '.join('?' * len(rs[0]))})", rs)
        return Counter(db.execute("SELECT type, subject, instantiates, path, value, info FROM validation_result")
                       .fetchall())
    finally:
        db.close()


def other(sql_type: str, v, n: int = 1):
    """A value of the same type that differs from v (and from the n-1 before it)."""
    if sql_type == "BIGINT":
        return v + n
    if sql_type == "BOOLEAN":
        return not v
    if sql_type == "DATE":
        return v + datetime.timedelta(days=n)
    return f"{v}{'~' * n}"


def stranger(sql_type: str, n: int = 1):
    """An id that no fact uses."""
    return {"BIGINT": -7_000_000 - n, "DATE": datetime.date(1900, 1, n)}.get(sql_type, f"~planted{n}")


def planted(model, rows: dict[str, list[tuple]]) -> dict[str, list[tuple]]:
    """The state with violations of every generic check planted, wherever the facts give a row to start from:
    a duplicate element, an element missing from its parent kind, a slot row of no element, a second value, a
    dangling arrow, values beyond the bounds or outside the enum or constant, a required or bounded multivalued
    slot left empty, too many values, and a twin on each unique key."""
    out = {t: list(r) for t, r in rows.items()}
    for k, kind in model.kinds.items():
        ids, idt = [r[0] for r in out.get(k, [])], emit.id_type(model, k)
        if not ids:
            continue
        out[k].append((ids[0],))
        if kind.parent:
            out[k].append((stranger(idt),))
        for s in kind.slots.values():
            t = out.get(s.table) or []
            if not t:
                continue
            (i, v), last = t[0], t[-1][0]
            if (s.required or s.minimum_cardinality) and last != i:
                t = [r for r in t if r[0] != last]
            t.append((stranger(idt), v))
            if not s.multivalued:
                t.append((i, other(s.sql_type, v)))
            elif s.maximum_cardinality is not None and s.sql_type != "BOOLEAN":
                t += [(i, other(s.sql_type, v, n)) for n in range(1, s.maximum_cardinality + 2)]
            if s.arrow:
                t.append((i, stranger(s.sql_type, 2)))
            if s.minimum is not None:
                t.append((i, s.minimum - 1))
            if s.maximum is not None:
                t.append((i, s.maximum + 1))
            out[s.table] = t
        for n, (_, slots) in enumerate(kind.unique_keys, 3):
            twin = stranger(idt, n)
            out[k].append((twin,))
            for sn in slots:
                table = model.slot(k, sn).table
                out[table] = out.get(table, []) + [(twin, v) for i, v in out.get(table, []) if i == ids[0]]
    return out


def rows_of(doc: str) -> dict[str, list[tuple]]:
    return {t: [tuple(r.values()) for r in rs] for t, rs in json.loads(doc).items()}


@pytest.mark.parametrize("pack_dir", PACKS, ids=[str(p.relative_to(REPO / "examples")) for p in PACKS])
def test_bundled_checks_find_the_planted_violations_once(pack_dir):
    model = pack.read(pack_dir)
    if model.meta.get("theory"):
        pytest.skip("a theory has no fact states: its checks run in the packs that import it")
    files = emit.compile_pack(model, max_views=10**6)
    if not emit.integrity(model):
        pytest.skip("no checks")
    params = rows_of(files["engine/parameters.json"])
    states = [(kind, name, rows) for kind, name, _, rows in scenarios.fact_states(model, pack_dir)]
    assert states, "a pack without fact states proves nothing"
    states += [(kind, name + " +planted", planted(model, rows)) for kind, name, rows in states]
    found = 0
    for kind, name, rows in states:
        got = run([files["engine/tables.sql"], files["engine/integrity.sql"]], params | rows)
        assert max(got.values(), default=1) == 1, f"{kind} {name}: the bundled validation_result has duplicates"
        found += len(got)
        COVERED.update(r[0] for r in got if r[0] in checks.GENERIC)
    if (pack_dir / "diagnostics").is_dir():
        assert found, "the diagnostics show violations; none found proves nothing"


def test_every_generic_check_was_hit():
    """Runs after the packs: each generic check found violations somewhere."""
    if not COVERED:
        pytest.skip("run with the pack tests")
    print("violation rows per generic check:", dict(sorted(COVERED.items())))
    assert sorted(COVERED) == sorted(checks.GENERIC)
