"""Feldera reserves relation names even when quoted. Logical rows and evidence keep their names."""

import json
import shutil
from urllib.parse import parse_qs, urlsplit

import duckdb
import feldera

from rezono_compiler import emit, feldera_names, pack, rules_dl, rules_split
from rezono_compiler import rules as ir
from rezono_compiler.__main__ import main
from support import FIXTURE, REPO


def test_compiled_time_inputs_keep_their_logical_evidence():
    for name in ("platform", "subsidy"):
        model = pack.read(REPO / "examples" / name)
        files = emit.compile_pack(model)
        tables, checks = files["engine/tables.sql"], files["engine/integrity.sql"]
        assert 'CREATE TABLE "__rezono_interval"' in tables
        assert 'CREATE TABLE "interval"' not in tables
        assert 'FROM "__rezono_interval"' in checks
        assert "interval" in json.loads(files["engine/pipelines.json"])["pipelines"][0]["tables"]
        assert all("__rezono_interval" not in content for path, content in files.items()
                   if not (path.startswith("engine/") and path.endswith(".sql")))
        # The publisher evaluates the same integrity program on a logical DuckDB schema.
        with duckdb.connect() as db:
            db.execute(emit.DUCKDB_FUNCTIONS)
            db.execute(emit.duckdb(tables))
            db.execute(emit.duckdb(checks))
            db.execute("""INSERT INTO "interval" VALUES ('i')""")
            assert db.execute("""SELECT id FROM "rezono__element" WHERE kind = 'interval'""").fetchall() == [("i",)]


def test_split_reserved_view_keeps_columns_tags_and_transport(monkeypatch):
    program = rules_dl.read_program("""
.decl interval(interval: symbol)
interval(x) :- rezono_interval(x).
.decl kept(value: symbol)
kept(x) :- interval(x).
""", "rules/test.dl", {"rezono_interval": [("id", "string")]}, "neutral")
    prog = ir.load(program)
    producer, consumer = rules_split.plan(prog, [["interval"], ["kept"]])
    assert producer["exports"] == consumer["imports"] == ["interval"]
    physical = "__rezono_interval"
    source = rules_split.part_sql(prog, producer, witnesses=True)
    sink = rules_split.part_sql(prog, consumer, witnesses=True)
    assert f'CREATE MATERIALIZED VIEW "{physical}"' in source
    assert f'CREATE TABLE "{physical}" ("interval" VARCHAR NOT NULL)' in sink
    with duckdb.connect() as db:
        db.execute(source.replace("CREATE MATERIALIZED VIEW", "CREATE VIEW"))
        db.execute("""INSERT INTO "rezono_interval" VALUES ('seen')""")
        assert db.execute('SELECT rel, a0 FROM "export__out"').fetchall() == [("interval", "seen")]
        assert db.execute(f'SELECT "interval" FROM "{physical}"').fetchall() == [("seen",)]
    with duckdb.connect() as db:
        db.execute(sink.replace("CREATE MATERIALIZED VIEW", "CREATE VIEW"))
        db.execute(f"""INSERT INTO "{physical}" VALUES ('seen')""")
        assert db.execute('SELECT * FROM "kept"').fetchall() == [("seen",)]
        assert db.execute('SELECT * FROM "kept__witness"').fetchall() == [("seen",)]

    calls = []

    def request(method, endpoint, body=None, raw=False):
        url = urlsplit(endpoint)
        calls.append((method, url.path, parse_qs(url.query), json.loads(body) if body else None))
        return "" if raw else {"token": "received"}

    monkeypatch.setattr(feldera, "call", request)
    updates = [{"insert": {"interval": "seen"}}, {"delete": {"interval": "seen"}}]
    base_updates = [{"insert": {"id": "other"}}]
    assert feldera.push("part", {"interval": updates, "rezono_interval": base_updates}) == ["received", "received"]
    assert [(path, body) for _, path, _, body in calls] == [
        ("/v0/pipelines/part/ingress/__rezono_interval", updates),
        ("/v0/pipelines/part/ingress/rezono_interval", base_updates),
    ]
    feldera.query("part", 'SELECT * FROM "interval"')
    assert calls[-1][2]["sql"] == [f'SELECT * FROM "{physical}"']


def test_facts_command_addresses_both_concrete_tables(tmp_path, capsys):
    model = shutil.copytree(FIXTURE, tmp_path / "pack")
    schema = model / "schema/minimal.yaml"
    with schema.open("a", encoding="utf-8") as stream:
        for name in ("Interval", "RezonoInterval"):
            stream.write(f"  {name}:\n    attributes:\n      id: {{identifier: true}}\n")
    facts = tmp_path / "facts.yaml"
    facts.write_text("interval: [{id: one}]\nrezono_interval: [{id: two}]\n")
    assert main(["facts", str(model), str(facts)]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "__rezono_interval": [{"insert": {"id": "one"}}],
        "rezono_interval": [{"insert": {"id": "two"}}],
    }


def test_only_relation_references_use_the_reserved_name_alias():
    sql = """-- FROM "interval"
/* JOIN "interval" */
DECLARE RECURSIVE VIEW "interval" ("interval" VARCHAR NOT NULL);
CREATE VIEW "kept" AS
SELECT "interval", 'FROM "interval"', 'escaped ''JOIN "interval"'''
FROM "interval" JOIN "rezono_interval" ON TRUE;
"""
    physical = sql.replace('VIEW "interval" (', 'VIEW "__rezono_interval" (')
    physical = physical.replace('FROM "interval" JOIN', 'FROM "__rezono_interval" JOIN')
    assert feldera_names.render(sql) == physical
    assert feldera_names.render(physical) == physical
    assert feldera_names.render(physical, feldera_names.LOGICAL) == sql
    assert feldera_names.render('SELECT * FROM "Interval"') == 'SELECT * FROM "Interval"'
