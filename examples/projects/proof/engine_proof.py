"""Engine proof for M1 (docs/roadmap.md): Feldera (incremental) against DuckDB (batch, full recompute).

Two axes: the number of input rows, and the weight of the rules. The rules of this example are written by
hand as SQL, because rules only compile from M2 on:
- light: 4 derived relations (depends_on with recursion, blocked with negation, open tasks per project);
- heavy: 12 derived relations that build on each other (negation over aggregates, aggregates over the closure).

The facts are synthetic and deterministic: P projects of 20 tasks each, as a tree with a few extra edges.
After loading, three single-fact changes follow, as a What-if would send them. After every step both
engines must agree on the size of every derived relation and the sum of every count.

    FELDERA_URL=http://localhost:8080 python examples/projects/proof/engine_proof.py light 400 100000
    FELDERA_URL=http://localhost:8080 python examples/projects/proof/engine_proof.py heavy 400 100000 1000000
"""

import csv
import os
import sys
import tempfile
import time
from pathlib import Path

import duckdb

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "compiler" / "tests"))
from support import compile_dir  # noqa: E402
from feldera import deploy, processed, push, query, stop  # noqa: E402

TASKS = 20
EDGES = ("SELECT t.v AS task, p.v AS prerequisite FROM dependency__task t "
         "JOIN dependency__prerequisite p ON p.id = t.id")
BLOCKED = ("SELECT DISTINCT d.task FROM depends_on d WHERE d.prerequisite NOT IN "
           "(SELECT id FROM task__status WHERE v = 'done')")
OPEN = ("SELECT p.v AS project, COUNT(*) AS n FROM task__project p JOIN task__status s ON s.id = p.id "
        "WHERE s.v = 'open' GROUP BY p.v")
# The light program is byte-identical to the one measured before, so Feldera can reuse its binary.
FELDERA_RULES = f"""
CREATE LOCAL VIEW edge AS {EDGES};
DECLARE RECURSIVE VIEW depends_on (task VARCHAR NOT NULL, prerequisite VARCHAR NOT NULL);
CREATE MATERIALIZED VIEW depends_on AS
SELECT task, prerequisite FROM edge
UNION
SELECT d.task, e.prerequisite FROM depends_on d JOIN edge e ON e.task = d.prerequisite;
CREATE MATERIALIZED VIEW blocked AS {BLOCKED};
CREATE MATERIALIZED VIEW open_tasks AS {OPEN};
"""
HEAVY = [
    ("ready", "SELECT s.id AS task FROM task__status s WHERE s.v = 'open' AND s.id NOT IN (SELECT task FROM blocked)"),
    ("blocked_per_project", "SELECT p.v AS project, COUNT(*) AS n FROM blocked b "
                            "JOIN task__project p ON p.id = b.task GROUP BY p.v"),
    ("ready_per_project", "SELECT p.v AS project, COUNT(*) AS n FROM ready r "
                          "JOIN task__project p ON p.id = r.task GROUP BY p.v"),
    ("stalled_project", "SELECT o.project FROM open_tasks o "
                        "WHERE o.project NOT IN (SELECT project FROM ready_per_project)"),
    ("dependents", "SELECT prerequisite AS task, COUNT(*) AS n FROM depends_on GROUP BY prerequisite"),
    ("bottleneck", "SELECT d.task FROM dependents d JOIN task__status s ON s.id = d.task "
                   "WHERE s.v = 'open' AND d.n > 3"),
    ("cross_project", "SELECT e.task, e.prerequisite FROM edge e JOIN task__project a ON a.id = e.task "
                      "JOIN task__project b ON b.id = e.prerequisite WHERE a.v <> b.v"),
    ("done_project", "SELECT id AS project FROM project WHERE id NOT IN (SELECT project FROM open_tasks)"),
]
COUNTED = {"open_tasks", "blocked_per_project", "ready_per_project", "dependents"}


def relations(weight):
    return ["depends_on", "blocked", "open_tasks"] + ([n for n, _ in HEAVY] if weight == "heavy" else [])


def feldera_program(tables, weight):
    extra = "".join(f"CREATE MATERIALIZED VIEW {n} AS {q};\n" for n, q in HEAVY) if weight == "heavy" else ""
    return tables + FELDERA_RULES + extra


def duckdb_views(db, weight):
    db.execute(f"CREATE VIEW edge AS {EDGES}")
    db.execute("CREATE VIEW depends_on AS WITH RECURSIVE r(task, prerequisite) AS ("
               "SELECT task, prerequisite FROM edge UNION "
               "SELECT r.task, e.prerequisite FROM r JOIN edge e ON e.task = r.prerequisite) SELECT * FROM r")
    db.execute(f"CREATE VIEW blocked AS {BLOCKED}")
    db.execute(f"CREATE VIEW open_tasks AS {OPEN}")
    for n, q in HEAVY if weight == "heavy" else []:
        db.execute(f"CREATE VIEW {n} AS {q}")


def signature_sql(weight):
    parts = []
    for r in relations(weight):
        parts.append(f"(SELECT COUNT(*) FROM {r}) AS c{len(parts)}")
        if r in COUNTED:
            parts.append(f"(SELECT COALESCE(SUM(n), 0) FROM {r}) AS c{len(parts)}")
    return "SELECT " + ", ".join(parts)


def facts(projects):
    """Rows per table: every project has a tree of tasks (task i waits on task (i-1)//2) and a few extra edges."""
    rows = {t: [] for t in ("project", "project__name", "project__budget", "task", "task__project", "task__name",
                            "task__status", "dependency", "dependency__task", "dependency__prerequisite")}
    for p in range(projects):
        pid = f"p{p}"
        rows["project"].append((pid,))
        rows["project__name"].append((pid, pid))
        rows["project__budget"].append((pid, 0))
        for i in range(TASKS):
            t = f"{pid}t{i}"
            rows["task"].append((t,))
            rows["task__project"].append((t, pid))
            rows["task__name"].append((t, t))
            rows["task__status"].append((t, "done" if (p * 7 + i * 3) % 5 < 2 else "open"))
            for j in ([(i - 1) // 2] if i else []) + ([i - 2] if i >= 2 and i % 4 == 0 else []):
                d = f"{t}d{j}"
                rows["dependency"].append((d,))
                rows["dependency__task"].append((d, t))
                rows["dependency__prerequisite"].append((d, f"{pid}t{j}"))
    return rows


def changes(projects):
    """Three single-fact changes in the middle project, as (name, deletes, inserts)."""
    p = f"p{projects // 2}"
    old = "done" if (projects // 2 * 7) % 5 < 2 else "open"
    new = "open" if old == "done" else "done"
    edge = f"{p}t1d0"
    extra = f"{p}t19x"
    return [
        ("root task flips status", {"task__status": [(f"{p}t0", old)]}, {"task__status": [(f"{p}t0", new)]}),
        ("one dependency removed", {"dependency": [(edge,)], "dependency__task": [(edge, f"{p}t1")],
                                    "dependency__prerequisite": [(edge, f"{p}t0")]}, {}),
        ("one dependency added across projects", {}, {"dependency": [(extra,)], "dependency__task": [(extra, f"{p}t19")],
                                                      "dependency__prerequisite": [(extra, "p0t0")]}),
    ]


REPS = 5
FULL_SET_LIMIT = 300_000


def median(xs):
    return sorted(xs)[len(xs) // 2]


def derived_rows(weight, signature):
    """The number of derived rows: the count columns of the signature, not the sums."""
    out, i = 0, 0
    for r in relations(weight):
        out += signature[i]
        i += 2 if r in COUNTED else 1
    return out


def same_sets(name, db, weight):
    """Compare every derived relation between the engines, row by row."""
    for r in relations(weight):
        got = sorted(tuple(row.values()) for row in query(name, f"SELECT * FROM {r}"))
        want = sorted(tuple(row) for row in db.execute(f"SELECT * FROM {r}").fetchall())
        assert got == want, f"{r}: Feldera and DuckDB differ"


def cols(table):
    return ("id",) if "__" not in table else ("id", "v")


def updates(deletes, inserts):
    out = {}
    for kind, tables in (("delete", deletes), ("insert", inserts)):
        for table, rows in tables.items():
            out.setdefault(table, []).extend({kind: dict(zip(cols(table), r))} for r in rows)
    return out


def feldera_signature(name, weight):
    return tuple(int(v) for v in query(name, signature_sql(weight))[0].values())


def duckdb_load(db, rows, tmp):
    for table, rs in rows.items():
        f = tmp / f"{table}.csv"
        with open(f, "w", newline="") as fh:
            csv.writer(fh).writerows(rs)
        db.execute(f"COPY {table} FROM '{f}' (HEADER false)")


def duckdb_apply(db, deletes, inserts):
    for table, rs in deletes.items():
        for r in rs:
            db.execute(f"DELETE FROM {table} WHERE " + " AND ".join(f"{c} = ?" for c in cols(table)), r)
    for table, rs in inserts.items():
        db.executemany(f"INSERT INTO {table} VALUES ({', '.join('?' * len(rs[0]))})", rs)


def run(weight, target, tables, profile):
    projects = max(1, round(target / (3 + TASKS * 4 + 3 * 23)))
    rows = facts(projects)
    n_rows = sum(len(r) for r in rows.values())
    name = f"rede-proof-{weight}-{profile}"
    compiled = deploy(name, feldera_program(tables, weight), profile)
    print(f"\n{weight}, {profile}, {n_rows} input rows ({projects} projects): Feldera compile {compiled:.0f} s",
          flush=True)
    with tempfile.TemporaryDirectory() as t:
        db = duckdb.connect()
        db.execute(tables)
        duckdb_views(db, weight)
        start = time.time()
        duckdb_load(db, rows, Path(t))
        load = time.time() - start
        start = time.time()
        expect = db.execute(signature_sql(weight)).fetchone()
        batch = time.time() - start
        start = time.time()
        processed(name, push(name, updates({}, rows)))
        incr = time.time() - start
        assert feldera_signature(name, weight) == tuple(expect), "load"
        derived = derived_rows(weight, expect)
        by_row = derived <= FULL_SET_LIMIT
        if by_row:
            same_sets(name, db, weight)
        print(f"  load: derived rows {derived} | DuckDB load {load:.2f} s, recompute {batch * 1000:.0f} ms"
              f" | Feldera load to all views {incr:.2f} s", flush=True)
        for label, deletes, inserts in changes(projects):
            times = {"DuckDB": [], "Feldera": []}
            for rep in range(REPS * 2):
                dels, ins = (deletes, inserts) if rep % 2 == 0 else (inserts, deletes)
                start = time.time()
                duckdb_apply(db, dels, ins)
                expect = db.execute(signature_sql(weight)).fetchone()
                times["DuckDB"].append(time.time() - start)
                start = time.time()
                processed(name, push(name, updates(dels, ins)))
                times["Feldera"].append(time.time() - start)
                assert feldera_signature(name, weight) == tuple(expect), (label, rep)
                if by_row and rep in (0, REPS * 2 - 1):  # after the change, and after undoing it
                    same_sets(name, db, weight)
            print(f"  {label} (median of {REPS * 2}, apply and undo): DuckDB apply + recompute "
                  f"{median(times['DuckDB']) * 1000:.0f} ms | Feldera delta to all views "
                  f"{median(times['Feldera']) * 1000:.0f} ms", flush=True)
        print("  compared by count and sum after every step"
              + (", row by row after the load and after the first apply and last undo of each change" if by_row else ""),
              flush=True)
    stop(name)


def main(args):
    weight, profile = args[0], os.environ.get("FELDERA_PROFILE", "optimized")
    with tempfile.TemporaryDirectory() as t:
        tables = compile_dir(REPO / "examples" / "projects", Path(t))["engine/tables.sql"]
    for target in [int(a) for a in args[1:]] or [400]:
        run(weight, target, tables, profile)


if __name__ == "__main__":
    main(sys.argv[1:])
