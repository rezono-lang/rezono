"""Admission on a small bundle of its own: no compiler. Every refusal is reported; a batch needs a source; the
same delivery is admitted once; and the package imports nothing of the compiler."""

from __future__ import annotations

import ast
import datetime
import subprocess
import sys
from pathlib import Path

from rezono_admission import Admission, Schema, rows

HERE = Path(__file__).resolve().parents[1]
BUNDLE = {
    "format": "rezono.schema-bundle/1",
    "pack": {"id": "t", "version": "1", "default_language": "en"},
    "kinds": [{"id": "thing", "identifier": "id", "id_type": "text"},
              {"id": "part", "id_type": "text"},
              {"id": "shape", "abstract": True, "identifier": "id", "id_type": "text"}],
    "attributes": [{"id": "thing.size", "kind": "thing", "name": "size", "table": "thing__size", "type": "integer"},
                   {"id": "thing.on", "kind": "thing", "name": "on", "table": "thing__on", "type": "date"},
                   {"id": "part.label", "kind": "part", "name": "label", "table": "part__label", "type": "text"}],
    "arrows": [{"id": "thing.parts", "kind": "thing", "name": "parts", "table": "thing__parts", "target": "part",
                "multivalued": True, "inlined": True}],
}


def test_rows_and_every_refusal():
    schema = Schema(BUNDLE)
    got, refusals = rows(schema, {"thing": [{"id": "a", "size": 2, "on": "2026-11-12", "parts": [{"label": "x"}]}]})
    assert refusals == []
    assert got == {"part": [("a/thing.parts/1",)], "part__label": [("a/thing.parts/1", "x")],
                   "thing": [("a",)], "thing__on": [("a", datetime.date(2026, 11, 12))],
                   "thing__parts": [("a", "a/thing.parts/1")], "thing__size": [("a", 2)]}
    got, refusals = rows(schema, {"thing": [{"id": "a", "size": "2"}, {"size": 1}, {"id": "c", "colour": 1},
                                            {"id": "d", "size": 4}],
                                  "shape": [{"id": "s"}], "ghost": []})
    assert [(r.code, r.where) for r in refusals] == [
        ("wrong_type", "thing[1].size"), ("record_without_identifier", "thing[2]"), ("unknown_slot", "thing[3].colour"),
        ("kind_abstract", "shape[1]"), ("unknown_kind", "ghost")]
    assert got == {"thing": [("d",)], "thing__size": [("d", 4)]}, "the records beside a refused one are judged"
    assert {r.schema for r in refusals} == {schema.sha256}
    # Each refusal is a diagnostic of contracts/diagnostic.yaml (D15): an error with its code and place.
    assert refusals[0].diagnostic() == {"code": "wrong_type", "severity": "error", "where": "thing[1].size"}
    try:
        from rezono_contracts.diagnostic import DiagnosticList
    except ImportError:  # the generated types are not installed where admission alone runs
        return
    DiagnosticList.model_validate({"diagnostics": [r.diagnostic() for r in refusals]})


def test_a_batch_needs_a_source_and_one_delivery_is_admitted_once():
    a = Admission(Schema(BUNDLE))
    assert [r.code for r in a.admit({"thing": [{"id": "a"}]}, source="").refusals] == ["source_missing"]
    first = a.admit({"thing": [{"id": "a"}]}, source="feed", event="e1")
    assert first.admitted and first.rows == {"thing": [("a",)]}
    assert a.admit({"thing": [{"id": "a"}]}, source="feed", event="e1").duplicate
    assert a.admit({"thing": [{"id": "b"}]}, source="feed", event="e2").admitted
    assert a.admit({"thing": [{"id": "b"}]}, source="feed").admitted, "without an event key the rows are the key"
    assert a.admit({"thing": [{"id": "b"}]}, source="feed").duplicate
    refused = a.admit({"thing": [{"id": "c"}, {"id": "d", "size": "x"}]}, source="feed", event="e3")
    assert refused.rows == {} and not refused.admitted, "a batch is all or nothing"
    assert Admission(Schema(BUNDLE), a.seen).admit({"thing": [{"id": "a"}]}, source="feed", event="e1").duplicate


def test_admission_imports_nothing_of_the_compiler():
    # The owner's acceptance line: a fact never needs the compiler.
    for path in sorted((HERE / "rezono_admission").glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])
            assert not any(n.split(".")[0] == "rezono_compiler" for n in names), path.name
    probe = "import sys, rezono_admission; sys.exit(any(m.split('.')[0] == 'rezono_compiler' for m in sys.modules))"
    assert subprocess.run([sys.executable, "-c", probe], cwd=HERE).returncode == 0


def test_an_observer_sees_every_record_and_row_and_changes_nothing():
    # The compiler's sources need where each row comes from; a caller without an observer sees no difference.
    schema = Schema(BUNDLE)
    data = {"thing": [{"id": "a", "size": 2, "parts": [{"label": "x"}, {"label": "y"}]}, {"id": "b", "size": "2"}]}
    records, seen = [], []

    def on_record(kind, eid, context):
        records.append((kind, eid, context))
        return f"{context}>{eid}"

    def on_row(table, row, kind, eid, slot, context):
        seen.append((table, row, kind, eid, slot, context))

    assert rows(schema, data, on_record=on_record, on_row=on_row, context="top") == rows(schema, data)
    assert records == [("thing", "a", "top"), ("part", "a/thing.parts/1", "top>a"),
                       ("part", "a/thing.parts/2", "top>a"), ("thing", "b", "top")]
    assert ("part__label", ("a/thing.parts/2", "y"), "part", "a/thing.parts/2", "label", "top>a>a/thing.parts/2") in seen
    assert ("thing__parts", ("a", "a/thing.parts/1"), "thing", "a", "parts", "top>a") in seen
    assert ("thing", ("a",), "thing", "a", None, "top>a") in seen
    assert ("thing", ("b",), "thing", "b", None, "top>b") in seen, "rows before a refusal are seen, then discarded"
    assert not [s for s in seen if s[0] == "thing__size" and s[3] == "b"]
