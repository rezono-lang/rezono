"""Calendar equality needs the date from each linked record (decisions/independent-date-equality.md)."""

from contextlib import closing
from datetime import date
import json
from pathlib import Path
import shutil
from uuid import uuid4

import pytest
import yaml

import feldera
from rezono_compiler import batch, emit, facts, pack, rules, rules_sql
from support import FIXTURE


SOURCE = """
.decl same_day(record: symbol, reference: symbol)
same_day(record, reference) :- beta__alpha(record, reference), beta__observed(record, observed),
    alpha__expected(reference, expected), observed = expected.
"""
LEAP = date(2024, 2, 29)
NEXT = date(2024, 3, 1)
HIT = ("hit", "first", LEAP, LEAP)
CONTROL = ("control", "second", NEXT, NEXT)
TABLES = ("beta__alpha", "beta__observed", "alpha__expected")
COLUMNS = {"same_day": ("record", "reference"),
           "same_day__witness": ("v_record", "v_reference", "v_observed", "v_expected")}


@pytest.fixture
def dated_records(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = folder / "schema/minimal.yaml"
    document = yaml.safe_load(schema.read_bytes())
    alpha = document["classes"]["Alpha"]["attributes"]
    beta = document["classes"]["Beta"]["attributes"]
    alpha["expected"] = {"range": "date"}
    beta["observed"] = {"range": "date"}
    beta["alpha"].pop("required")
    schema.write_text(yaml.safe_dump(document), encoding="utf-8")
    data = {
        "alpha": [{"id": "first", "title": "one", "expected": "2024-02-29"},
                  {"id": "second", "title": "two", "expected": "2024-03-01"},
                  {"id": "undated", "title": "three"}],
        "beta": [{"id": "hit", "alpha": "first", "observed": "2024-02-29"},
                 {"id": "control", "alpha": "second", "observed": "2024-03-01"},
                 {"id": "before", "alpha": "first", "observed": "2024-02-28"},
                 {"id": "after", "alpha": "first", "observed": "2024-03-01"},
                 {"id": "undated-record", "alpha": "first"},
                 {"id": "undated-reference", "alpha": "undated", "observed": "2024-02-29"},
                 {"id": "unlinked", "observed": "2024-02-29"}],
    }
    admitted = facts.rows_of(pack.read(folder), data)
    return folder, {name: admitted[name] for name in TABLES}


def epochs(initial):
    yield "insert", initial, {HIT, CONTROL}
    for table, row in (("beta__alpha", ("hit", "first")), ("beta__observed", ("hit", LEAP)),
                       ("alpha__expected", ("first", LEAP))):
        yield "delete", {table: [row]}, {CONTROL}
        yield "insert", {table: [row]}, {HIT, CONTROL}


def test_calendar_oracle_for_linked_dates(dated_records):
    _, initial = dated_records
    rows = {name: set() for name in TABLES}
    for op, changes, expected in epochs(initial):
        for name, changed in changes.items():
            if op == "insert":
                rows[name].update(changed)
            else:
                for row in changed:
                    rows[name].remove(row)
        observed, requested = dict(rows["beta__observed"]), dict(rows["alpha__expected"])
        assert all(type(day) is date for day in (*observed.values(), *requested.values()))
        actual = {(record, ref, observed[record], requested[ref]) for record, ref in rows["beta__alpha"]
                  if record in observed and ref in requested and observed[record] == requested[ref]}
        assert actual == expected


def check_epoch(query, witnesses, *, json_dates=False):
    for relation, columns in COLUMNS.items():
        expected = [row[:2] for row in witnesses] if relation == "same_day" else list(witnesses)
        if json_dates and relation == "same_day__witness":
            expected = [(record, ref, obs.isoformat(), day.isoformat()) for record, ref, obs, day in expected]
        statement = "SELECT " + ", ".join(f'"{col}"' for col in columns) + f' FROM "{relation}"'
        assert sorted(query(statement, columns)) == sorted(expected), relation


@pytest.mark.xfail(strict=True, raises=pytest.RaisesExc(
    pack.CompileError, match=r"(alpha__expected|beta__observed) has a column"), reason=(
    "extra: Read decisions/independent-date-equality.md. Admit DATE equality in contracts/rules.yaml and "
    "compiler/rezono_compiler. Select this test in compiler/ci/run_feldera_oracle.sh, add it to the "
    "compiler-bound shard in compiler/ci/feldera_shards.py and leave it out of ORIGINAL there "
    "(ORIGINAL = EXPECTED - {INTERFACE, ..., <this test>}; recorded main runs before it stay complete evidence; "
    "scripts/feldera_admission.py stays unchanged). Lift this mark. If "
    "examples/test_calculation_engine_parity.py::test_feldera_calculations_match_duckdb_and_checker[subsidy] is already routed "
    "on main, also lift the strict marks on "
    "examples/test_live_feldera_shards.py::test_merge_preserves_all_live_cases_and_outcomes and "
    "examples/test_feldera_incident.py::test_classifier_uses_complete_reports_from_the_parallel_comparison; "
    "otherwise leave them. Verify the exact implementation revision on hosted Feldera before queue admission."))
def test_independent_date_equality(dated_records):
    folder, initial = dated_records
    (folder / "rules").mkdir()
    source = folder / "rules/match.dl"
    source.write_text(SOURCE, encoding="utf-8")
    model = pack.read(folder)
    program = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    contract = Path(__file__).resolve().parents[2] / "contracts/rules.yaml"
    assert "date" in yaml.safe_load(contract.read_bytes())["enums"]["ColumnType"]["permissible_values"]
    for name in ("alpha__expected", "beta__observed"):
        assert program.relations[name].key[1].type == "date"
    for operand in ('"2024-02-29"', "20240229"):
        source.write_text(SOURCE.replace("observed = expected", f"observed = {operand}"), encoding="utf-8")
        with pytest.raises(pack.CompileError):
            pack.read(folder)

    with closing(batch.connect(program, {})) as db:
        for op, changes, witnesses in epochs(initial):
            for name, changed in changes.items():
                for row in changed:
                    batch.apply(db, program, name, row, op)
            batch.compute(db, program, witnesses=True)
            check_epoch(lambda sql, cols: db.execute(sql).fetchall(), witnesses)

    sql = rules_sql.feldera(program, witnesses=True)
    for name in ("alpha__expected", "beta__observed"):
        table = next(line for line in sql.splitlines() if line.startswith(f'CREATE TABLE "{name}"'))
        assert '"v" DATE' in table
    if feldera.URL:
        pipeline = "rezono-date-equality-" + uuid4().hex
        feldera.deploy(pipeline, sql, profile="unoptimized", workers=2)
        try:
            def query(statement, columns):
                return [tuple(row[c] for c in columns) for row in feldera.query(pipeline, statement)]

            for op, changes, witnesses in epochs(initial):
                feldera.processed(pipeline, feldera.push(pipeline, facts.ingress(model, changes, op)))
                check_epoch(query, witnesses, json_dates=True)
        finally:
            feldera.stop(pipeline, delete=True)
