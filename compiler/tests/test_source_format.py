"""The source-format edit boundary (B13): the canonical writer, the source writer and the schema operations edit
fact, rule and calc files through `source_format`, and a second format fits the same interface (the Reckon stub,
tested with one fact edit)."""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

from rede_compiler import source_format, writer

REPO = Path(__file__).resolve().parents[2]
PACKS = sorted(p.parent for p in (REPO / "examples").rglob("pack.yaml") if "expected" not in p.parts)
FMT = source_format.YAML_DATALOG
operate_model = importlib.import_module("rede_compiler.operate.model")  # the package names a function `model`


def test_every_format_implements_the_whole_interface():
    for fmt in (source_format.YAML_DATALOG, source_format.RECKON_STUB):
        assert isinstance(fmt, source_format.SourceFormat)
        assert not inspect.isabstract(type(fmt))
    assert source_format.FORMATS == (source_format.YAML_DATALOG,)  # the stub writes no pack


def test_a_fact_file_has_its_format_and_another_path_is_refused():
    assert source_format.of("facts/items.yaml") is FMT
    for rel in ("facts/items.sources.yaml", "rules/main.dl", "reckon/items.rezono", "../facts/items.yaml"):
        with pytest.raises(writer.WriteError, match="no source format"):
            source_format.of(rel)


@pytest.mark.parametrize("pack_dir", PACKS, ids=[str(p.relative_to(REPO)) for p in PACKS])
def test_the_yaml_datalog_files_are_the_files_the_editors_read(pack_dir):
    dirs = ("facts", "scenarios", "diagnostics")
    assert FMT.fact_files(pack_dir, dirs) == [
        (f"{d}/{f.name}", f) for d in dirs for f in sorted((pack_dir / d).glob("*.yaml"))]
    assert FMT.rule_files(pack_dir) == [(f"rules/{f.name}", f) for f in sorted((pack_dir / "rules").glob("*.dl"))]
    assert FMT.calc_files(pack_dir) == [n for n in ("calc", "sweeps.yaml") if (pack_dir / n).exists()]


def test_the_schema_operations_find_their_files_through_the_boundary(tmp_path):
    (tmp_path / "facts").mkdir()
    (tmp_path / "facts" / "b.yaml").write_text("{}\n", "utf-8")
    (tmp_path / "facts" / "a.yaml").write_text("{}\n", "utf-8")
    (tmp_path / "rules").mkdir()
    (tmp_path / "rules" / "main.dl").write_text("// none\n", "utf-8")

    class Stub:  # only the directory matters to the file lists
        dir = tmp_path

    m = Stub()
    assert [rel for rel, _ in operate_model.fact_files(m)] == ["facts/a.yaml", "facts/b.yaml"]  # type: ignore[arg-type]
    assert [rel for rel, _ in operate_model.rule_files(m)] == ["rules/main.dl"]  # type: ignore[arg-type]
    assert [t.kind for t in operate_model.rule_tokens("a(x) :- b(x).\n", "rules/main.dl")][-1] == "end"


def test_the_yaml_implementation_is_the_canonical_writer():
    library = REPO / "examples" / "library"
    lay = writer.layout(library)
    rel, path = FMT.fact_files(library)[0]
    text = path.read_bytes().decode("utf-8")
    records = FMT.fact_records(text)
    kind = next(k for k, rs in records.items() if rs and lay.pack.kinds[lay.pack.root(k)].identifier)
    ident = lay.pack.kinds[lay.pack.root(kind)].identifier
    change = {"op": "delete", "file": rel, "kind": kind, "key": writer.to_json(records[kind][0][ident])}
    assert FMT.edit_fact(lay, text, change) == writer.apply_change(lay, text, change)
    assert records == writer.parse(text)[2]


# --- The Reckon stub ----------------------------------------------------------------------------------------

MODULE = """\
reckon 0
pack sample

kind Item
  since: Date

fact Item
  | id | since      |
  | a1 | 2020-01-01 |
  | a2 | n/a        |
"""


def test_the_reckon_stub_makes_one_fact_edit_and_its_undo_gives_the_same_bytes():
    stub = source_format.RECKON_STUB
    change = {"op": "set", "file": "reckon/sample.rezono", "kind": "item", "key": "a1", "slot": "since",
              "value": "2021-03-01"}
    text, undo = stub.edit_fact(None, MODULE, change)  # type: ignore[arg-type]  # the stub needs no layout
    assert text == MODULE.replace("| a1 | 2020-01-01 |", "| a1 | 2021-03-01 |")
    assert undo == {**change, "value": "2020-01-01"}
    assert stub.fact_records(text) == {"Item": [{"id": "a1", "since": "2021-03-01"}, {"id": "a2", "since": "n/a"}]}
    back, _ = stub.edit_fact(None, text, undo)  # type: ignore[arg-type]
    assert back.encode("utf-8") == MODULE.encode("utf-8")
    assert stub.fact_file("reckon/sample.rezono") and not stub.fact_file("facts/sample.yaml")


@pytest.mark.parametrize("change,message", [
    ({"op": "insert", "kind": "item", "key": "a3", "values": {}}, "stub"),
    ({"op": "set", "kind": "item", "key": "a2", "slot": "since", "value": "2020-01-01"}, "n/a"),
    ({"op": "set", "kind": "item", "key": "a1", "slot": "since", "value": "2020-01-01T00:00"}, "wider"),
    ({"op": "set", "kind": "item", "key": "a1", "slot": "since", "value": "a | b"}, "plain text"),
    ({"op": "set", "kind": "item", "key": "a9", "slot": "since", "value": "2020-01-01"}, "not found"),
    ({"op": "set", "kind": "other", "key": "a1", "slot": "since", "value": "2020-01-01"}, "no fact table"),
])
def test_the_reckon_stub_refuses_what_it_does_not_build(change, message):
    with pytest.raises(writer.WriteError, match=message):
        source_format.RECKON_STUB.edit_fact(None, MODULE, change)  # type: ignore[arg-type]


def test_the_reckon_stub_finds_module_files_and_refuses_rules(tmp_path):
    (tmp_path / "reckon" / "part").mkdir(parents=True)
    (tmp_path / "reckon" / "part" / "sample.rezono").write_text(MODULE, "utf-8")
    (tmp_path / "reckon" / "part" / "sample.json").write_text("{}", "utf-8")
    stub = source_format.RECKON_STUB
    assert [rel for rel, _ in stub.fact_files(tmp_path)] == ["reckon/part/sample.rezono"]
    assert stub.fact_files(tmp_path, ("scenarios",)) == []
    assert stub.rule_files(tmp_path) == [] and stub.calc_files(tmp_path) == []
    with pytest.raises(writer.WriteError, match="stub"):
        stub.rule_tokens("a(x).", "reckon/part/sample.rezono")
