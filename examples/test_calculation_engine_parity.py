"""Today's calculations of the example packs on Feldera, beside DuckDB and the checker.

Every example pack with calc/ and facts gives, at each of its fact states, on Feldera the same state, value
and reason per row of every calculation as DuckDB gives, and the same witnesses; the checker accepts the
witnesses Feldera gives. This holds for the current calculation form before the derivation form of the
first-release language reaches Feldera (docs/rezono/first-release-proposal.md, Feldera rule 5;
decisions/feldera-calculation-parity.md).

Offline the test checks that the comparison can run: every relation a witness is read from is readable on
Feldera, and the live oracle runs this test. With FELDERA_URL set it runs the comparison: the pack's
calculation pipeline gets, per fact state, the same input rows as the DuckDB run, and the rows Feldera holds
in its calculation views are read back into a database of the DuckDB schema, which the witness reader
(calc_sql.witnesses) and the checker read as they read the DuckDB run."""

import datetime
import json
import re
from collections import Counter
from pathlib import Path

import pytest

import feldera
from calcsupport import checked, connect, results
from rezono_compiler import calc, calc_sql, facts, feldera_names, scenarios
from rezono_compiler.sqltext import q

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
TEST = "examples/test_calculation_engine_parity.py::test_feldera_calculations_match_duckdb_and_checker"
SHARD = "subsidy"
# Every example pack with calculation rules and fact states, at any depth.
CALCULATED = sorted(p.parent for p in ROOT.rglob("pack.yaml")
                    if (p.parent / "calc").is_dir() and (p.parent / "facts").is_dir() and "expected" not in p.parts)


class MissingFelderaCalculationParity(LookupError):
    """A calculation relation that a witness is read from is not readable on Feldera, or the live oracle does
    not run this comparison."""


def name(p: Path) -> str:
    return p.relative_to(ROOT).as_posix()


def test_the_calculated_examples_are_found():
    assert ROOT / "subsidy" in CALCULATED, "the subsidy example evaluates the award and payment difference"


def read_relations(prog) -> list[str]:
    """Every calculation relation the witness reader reads: each rule's view, each version's view and each
    version's witness relation (calc_sql.witnesses)."""
    return ([prog.engine[r] for r in prog.rules]
            + [n for v in prog.versions.values() for n in (v.engine, calc_sql.witness_name(v))])


def readable(sql: str) -> set[str]:
    return set(re.findall(r'(?m)^CREATE MATERIALIZED VIEW ("(?:""|[^"])*")', sql))


def routed(example: Path) -> list[str]:
    """What the live oracle lacks to run this test for the pack: the selector, the shard, and not ORIGINAL."""
    import sys

    sys.path.insert(0, str(REPO / "compiler" / "ci"))
    import feldera_shards

    node = f"{TEST}[{name(example)}]"
    runner = (REPO / "compiler" / "ci" / "run_feldera_oracle.sh").read_text(encoding="utf-8")
    gaps = []
    if not re.search(rf"(?m)^\s*{re.escape(TEST)}\s*$", runner):
        gaps.append(f"compiler/ci/run_feldera_oracle.sh does not select {TEST}")
    if node not in feldera_shards.SHARDS[SHARD]:
        gaps.append(f"compiler/ci/feldera_shards.py does not route {node} in the {SHARD} shard")
    if node in feldera_shards.ORIGINAL:
        gaps.append(f"compiler/ci/feldera_shards.py counts {node} in ORIGINAL")
    return gaps


def changes(before, after):
    old, new = Counter(before), Counter(after)
    for op, counts in (("delete", old - new), ("insert", new - old)):
        if counts:
            yield op, sorted(counts.elements(), key=repr)


def cell(value):
    return value.isoformat() if isinstance(value, datetime.date) else value


def table_rows(db, table) -> tuple[list[str], list[tuple]]:
    cur = db.execute(f"SELECT * FROM {q(table)}")
    return [c[0] for c in cur.description], [tuple(cell(v) for v in r) for r in cur.fetchall()]


def subjects(db, view) -> list[str]:
    return sorted(str(r[0]) for r in db.execute(f"SELECT subject FROM {q(view)}").fetchall())


def from_feldera(reference, inputs: list[str], views: dict[str, list[dict]]):
    """A database with the reference's schema for the calculation's inputs and views: the input rows as the
    reference holds them (Feldera got the same), and the view rows as Feldera holds them."""
    import duckdb

    db = duckdb.connect()
    for table in [*inputs, *views]:
        columns = [(c, t) for c, t, *_ in reference.execute(f"DESCRIBE {q(table)}").fetchall()]
        db.execute(f"CREATE TABLE {q(table)} ({', '.join(f'{q(c)} {t}' for c, t in columns)})")
        if table in views:
            rows = [tuple({k.lower(): v for k, v in row.items()}[c.lower()] for c, _ in columns)
                    for row in views[table]]
        else:
            rows = reference.execute(f"SELECT * FROM {q(table)}").fetchall()
        if rows:
            names = ", ".join(q(c) for c, _ in columns)
            db.executemany(f"INSERT INTO {q(table)} ({names}) VALUES ({', '.join('?' * len(columns))})", rows)
    return db


@pytest.mark.xfail(strict=True, raises=MissingFelderaCalculationParity, reason=(
    "M3: the decision on the derivation form of the first-release language (rezono 1) is pending; before that "
    "form reaches Feldera, today's calculations must agree there with DuckDB and the checker "
    "(docs/rezono/first-release-proposal.md, Feldera rule 5; decisions/feldera-calculation-parity.md). "
    "Missing: compiler/rezono_compiler/calc_sql.py writes each calculation version and its witness relation "
    "(calc__<rule>__<version>, calc__<rule>__<version>__witness) as a plain CREATE VIEW in engine/calc.sql, so "
    "Feldera cannot be queried for them; every rule view, version view and witness relation must be a "
    "CREATE MATERIALIZED VIEW there. Missing: the live route; select this test in "
    "compiler/ci/run_feldera_oracle.sh, add its case to the subsidy shard in compiler/ci/feldera_shards.py "
    "and leave it out of ORIGINAL there (scripts/feldera_admission.py stays unchanged). Lift this mark. If "
    "compiler/tests/test_recorded_dates.py::test_independent_date_equality is already routed on main, also lift "
    "the strict marks on examples/test_live_feldera_shards.py::test_merge_preserves_all_live_cases_and_outcomes "
    "and examples/test_feldera_incident.py::test_classifier_uses_complete_reports_from_the_parallel_comparison; "
    "otherwise leave them. Verify the exact implementation revision on hosted Feldera before queue admission."))
@pytest.mark.parametrize("example", CALCULATED, ids=name)
def test_feldera_calculations_match_duckdb_and_checker(example, committed_packs):
    model = committed_packs.model(example)
    files = committed_packs.compiled(example)
    prog = calc.build(model, model.calc)
    plan = json.loads(files["engine/pipelines.json"])
    part = next(p for p in plan["pipelines"] if "engine/calc.sql" in p["sql"])
    unreadable = sorted(r for r in read_relations(prog)
                        if feldera_names.quoted(r) not in readable(files["engine/calc.sql"]))
    gaps = ([f"not readable on Feldera (engine/calc.sql): {unreadable}"] if unreadable else []) + routed(example)
    if gaps:
        raise MissingFelderaCalculationParity(f"{name(example)}: " + "; ".join(gaps))
    if not feldera.URL:
        return

    evaluation = calc_sql.rows(prog)
    initial = json.loads(files["engine/parameters.json"]) | json.loads(files["engine/calc.json"])
    fact_tables = part["tables"]
    views = read_relations(prog)
    pipeline = f"rezono-calc-parity-{example.name}"
    feldera.deploy(pipeline, "\n".join(files[path] for path in part["sql"]), profile="unoptimized", workers=2)
    try:
        previous: dict[str, list] = {}
        delta = {t: [{"insert": r} for r in rs] for t, rs in initial.items() if t in fact_tables}
        for label, rows in scenarios.states(model, example):
            reference = connect(model, prog, rows | {t: [tuple(r.values()) for r in rs] for t, rs in evaluation.items()})
            for table in fact_tables:
                for op, changed in changes(previous.get(table, []), rows.get(table, [])):
                    delta.setdefault(table, []).extend(facts.ingress(model, {table: changed}, op)[table])
                previous[table] = rows.get(table, [])
            for table in part["imports"]:
                columns, now = table_rows(reference, table)
                for op, changed in changes(previous.get(table, []), now):
                    delta.setdefault(table, []).extend({op: dict(zip(columns, r))} for r in changed)
                previous[table] = now
            feldera.processed(pipeline, feldera.push(pipeline, delta))
            delta = {}
            held = from_feldera(reference, [*fact_tables, *part["imports"]],
                                {v: feldera.read_relation(pipeline, v) for v in views})
            with feldera.comparing():
                for view in views:  # a missing row of a witness relation leaves its version's witness untraceable
                    assert subjects(held, view) == subjects(reference, view), (label, view)
                assert results(held, prog) == results(reference, prog), label
                got_witnesses = calc_sql.witnesses(held, prog)
                assert got_witnesses == calc_sql.witnesses(reference, prog), label
                assert checked(held, prog, got_witnesses) == [], label
    finally:
        feldera.stop(pipeline)
