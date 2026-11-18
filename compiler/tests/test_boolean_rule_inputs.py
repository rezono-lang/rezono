"""A boolean observation has three distinguishable cases (decisions/boolean-rule-inputs.md)."""

import json
import shutil
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest
import yaml

import feldera
from rezono_compiler import batch, emit, facts, pack, rules, rules_sql
from support import FIXTURE


SOURCE = """
.decl observed_flag(item: symbol, value: boolean)
observed_flag(item, value) :- alpha(item), alpha__flag(item, value).
.decl confirmed(item: symbol)
confirmed(item) :- observed_flag(item, value), value = TRUE.
.decl incomplete(item: symbol)
incomplete(item) :- observed_flag(item, value), value = FALSE.
"""


@pytest.fixture
def observation_pack(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = folder / "schema/minimal.yaml"
    document = yaml.safe_load(schema.read_bytes())
    document["classes"]["Alpha"]["attributes"]["flag"] = {"range": "boolean"}
    schema.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return folder


def records(keep_false):
    return {"alpha": [{"id": "a", "title": "one", "flag": True},
                      {"id": "b", "title": "two", **({"flag": False} if keep_false else {})},
                      {"id": "c", "title": "three"}]}


def expected(keep_false):
    yes = {("a", True)}
    no = {("b", False)} if keep_false else set()
    return {"observed_flag": yes | no, "observed_flag__witness": yes | no,
            "confirmed": {("a",)}, "confirmed__witness": yes,
            "incomplete": {("b",)} if keep_false else set(), "incomplete__witness": no}


def test_optional_boolean_admission_preserves_explicit_false(observation_pack):
    model = pack.read(observation_pack)
    for keep_false in (True, False):
        data = facts.rows_of(model, records(keep_false))
        assert set(data["alpha"]) == {("a",), ("b",), ("c",)}
        assert set(data["alpha__flag"]) == expected(keep_false)["observed_flag"]
        assert all(type(v) is bool for _, v in data["alpha__flag"])


def check_observations(query, keep_false):
    for relation, want in expected(keep_false).items():
        cols = ("v_item", "v_value") if relation.endswith("__witness") else (
            ("item", "value") if relation == "observed_flag" else ("item",))
        statement = 'SELECT ' + ', '.join(f'"{c}"' for c in cols) + f' FROM "{relation}"'
        rows = list(query(statement, cols))
        assert len(rows) == len(want) and set(rows) == want, (relation, rows)
        assert all(type(row[1]) is bool for row in rows if len(row) == 2), relation


def test_native_boolean_rule_inputs(observation_pack):
    folder = observation_pack / "rules"
    folder.mkdir()
    source = folder / "observation.dl"
    # Ordinary existing rule syntax isolates the input-column boundary first.
    source.write_text(".decl observed(item: symbol)\nobserved(item) :- alpha__flag(item, _).\n", encoding="utf-8")
    pack.read(observation_pack)
    source.write_text(SOURCE, encoding="utf-8")
    model = pack.read(observation_pack)
    contract = Path(__file__).resolve().parents[2] / "contracts/rules.yaml"
    assert "boolean" in yaml.safe_load(contract.read_bytes())["enums"]["ColumnType"]["permissible_values"]
    program = rules.load(json.loads(emit.compile_pack(model)["ir/rules.json"]))
    for name in ("alpha__flag", "observed_flag"):
        assert program.relations[name].key[1].type == "boolean"

    before = facts.rows_of(model, records(True))
    removed = {"alpha__flag": [("b", False)]}
    # The record itself survives the retraction.
    with closing(batch.connect(program, before)) as db:
        for keep_false in (True, False):
            if not keep_false:
                batch.apply(db, program, "alpha__flag", ("b", False), "delete")
            batch.compute(db, program, witnesses=True)
            check_observations(lambda sql, cols: db.execute(sql).fetchall(), keep_false)

    sql = rules_sql.feldera(program, witnesses=True)
    table = next(line for line in sql.splitlines() if line.startswith('CREATE TABLE "alpha__flag"'))
    assert '"v" BOOLEAN' in table
    for invalid in ('value = "true"', "value = 1", "value < TRUE"):
        source.write_text(SOURCE.replace("value = TRUE", invalid), encoding="utf-8")
        with pytest.raises(pack.CompileError):
            pack.read(observation_pack)
    source.write_text(SOURCE, encoding="utf-8")
    if feldera.URL:
        name = "rezono-boolean-input-" + uuid4().hex
        feldera.deploy(name, sql, profile="unoptimized", workers=2)
        try:
            def query(statement, cols):
                return [tuple(row[c] for c in cols) for row in feldera.query(name, statement)]
            initial = {key: before[key] for key in ("alpha", "alpha__flag")}
            for keep_false, inputs, operation in ((True, initial, "insert"),
                                                  (False, removed, "delete")):
                feldera.processed(name, feldera.push(name, facts.ingress(model, inputs, operation)))
                check_observations(query, keep_false)
        finally:
            feldera.stop(name)
            feldera.call("DELETE", f"/v0/pipelines/{name}")
