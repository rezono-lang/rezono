"""S25 base-row sources: canonical metadata never becomes engine data."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_compiler import emit, facts, pack, scenarios, sources, writer
from rezono_compiler.__main__ import main

FIXTURE = Path(__file__).parent / "fixtures" / "minimal"
DEFAULT = {"kind": "git", "name": "example/model", "revision": "a" * 40, "position": "corpus/snapshot.json"}


@pytest.fixture
def fixture(tmp_path):
    root = Path(shutil.copytree(FIXTURE, tmp_path / "pack"))
    (root / "facts").mkdir()
    (root / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, size: 1}\n", encoding="utf-8")
    return root


def metadata(root, value):
    (root / "facts/data.sources.yaml").write_text(yaml.safe_dump(value), encoding="utf-8")


def entries(root):
    return sources.read(pack.read(root), root)


def by_row(root):
    return {(e["row"]["relation"], e["row"]["key"]): e for e in entries(root)}


def test_implicit_lines_and_duplicate_rows_preserve_all_sources(fixture):
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, size: 1}\n  - {id: a, title: Alpha, size: 1}\n", encoding="utf-8")
    result = entries(fixture)
    assert len(result) == 3
    assert all(e["sources"] == [{"kind": "pack", "name": "facts/data.yaml", "position": n} for n in ["2", "3"]] for e in result)
    assert facts.load(pack.read(fixture), fixture / "facts/data.yaml")["alpha"] == [("a",), ("a",)]
    assert sources.compile_sources(pack.read(fixture), fixture) == canonical_json(result) + "\n"


def test_record_cell_precedence_canonical_union_and_reason(fixture):
    record = {"of": {"kind": "alpha", "id": "a"}, "position": "/entities/0", "reason": "exception.alpha"}
    metadata(fixture, {"default": DEFAULT | {"position": "corpus/snapshot.json#/old"}, "records": [record, record,
        record | {"position": "/entities/1"},
        {"of": {"kind": "alpha", "id": "a", "slot": "size"}, "position": "config/values.json#/0"}]})
    rows = by_row(fixture)
    expected = [DEFAULT | {"position": "corpus/snapshot.json#/entities/0"}, DEFAULT | {"position": "corpus/snapshot.json#/entities/1"}]
    assert rows[("alpha", '["a"]')]["sources"] == expected
    assert rows[("alpha__title", '["a","Alpha"]')]["reason"] == "exception.alpha"
    assert rows[("alpha__size", '["a","1"]')]["sources"] == [DEFAULT | {"position": "config/values.json#/0"}]


@pytest.mark.parametrize("kind", ["query", "tool", "person"])
def test_non_file_positions_are_literal(fixture, kind):
    metadata(fixture, {"default": {"kind": kind, "name": "input", "position": "base"}, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "position": "/literal"}]})
    assert all(e["sources"][0]["position"] == "/literal" for e in entries(fixture))


@pytest.mark.parametrize("kind", ["pack", "scenario"])
def test_other_inherited_file_sources_compose_pointers(fixture, kind):
    metadata(fixture, {"default": {"kind": kind, "name": "input", "position": "facts/base.yaml#/old"}, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "position": "/alpha/0"}]})
    assert all(e["sources"][0]["position"] == "facts/base.yaml#/alpha/0" for e in entries(fixture))


def test_complete_locator_with_changed_source_stays_exact(fixture):
    metadata(fixture, {"default": DEFAULT, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "name": "other/model", "position": "other/file.json#/x"}]})
    assert all(e["sources"] == [DEFAULT | {"name": "other/model", "position": "other/file.json#/x"}] for e in entries(fixture))


def test_source_union_across_files_is_sorted_deduplicated_and_conflicting_reasons_block(fixture):
    (fixture / "facts/other.yaml").write_bytes((fixture / "facts/data.yaml").read_bytes())
    metadata(fixture, {"default": DEFAULT})
    (fixture / "facts/other.sources.yaml").write_bytes((fixture / "facts/data.sources.yaml").read_bytes())
    assert all(len(e["sources"]) == 1 for e in entries(fixture))
    metadata(fixture, {"default": DEFAULT, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "reason": "one"},
        {"of": {"kind": "alpha", "id": "a"}, "reason": "two"}]})
    with pytest.raises(facts.LoadError, match="different reasons"):
        entries(fixture)


@pytest.mark.parametrize("override", [{"name": "other", "position": "/x"}, {"kind": "pack", "position": "/x"}])
def test_changed_source_does_not_silently_inherit_file(fixture, override):
    metadata(fixture, {"default": DEFAULT, "records": [{"of": {"kind": "alpha", "id": "a"}} | override]})
    with pytest.raises(facts.LoadError, match="ambiguous source pointer"):
        entries(fixture)


@pytest.mark.parametrize("default", [DEFAULT | {"position": "12"}, DEFAULT | {"position": "../outside.json"}])
def test_ambiguous_pointer_requires_full_locator(fixture, default):
    metadata(fixture, {"default": default, "records": [{"of": {"kind": "alpha", "id": "a"}, "position": "/x"}]})
    with pytest.raises(facts.LoadError, match="ambiguous source pointer"):
        entries(fixture)


@pytest.mark.parametrize("value, message", [
    ({"records": []}, "no source"),
    ({"default": {"kind": "pack", "name": "x"}}, "needs kind"),
    ({"default": {"kind": "git", "name": "x", "position": "file"}}, "git/proposal a revision"),
    ({"default": {"kind": "proposal", "name": "x", "position": "1"}}, "git/proposal a revision"),
    ({"default": DEFAULT | {"unknown": "x"}}, "needs kind"),
    ({"default": DEFAULT, "records": [{"of": {"kind": "alpha", "id": "absent"}}]}, "names no fact"),
    ({"default": DEFAULT, "records": [{"of": {"kind": "alpha", "id": "a", "slot": "unknown"}}]}, "no slot"),
])
def test_invalid_metadata_blocks_all_fact_readers(fixture, value, message):
    metadata(fixture, value)
    model = pack.read(fixture)
    for read in [lambda: sources.read(model, fixture), lambda: facts.load(model, fixture / "facts/data.yaml"),
                 lambda: scenarios.fact_states(model, fixture)]:
        with pytest.raises(facts.LoadError, match=message):
            read()
    assert main(["check", str(fixture)]) == 1


def test_orphan_sidecar_blocks_enumeration(fixture):
    (fixture / "facts/lost.sources.yaml").write_text("default: {}", encoding="utf-8")
    with pytest.raises(facts.LoadError, match="no companion fact file"):
        facts.files(fixture)
    assert main(["check", str(fixture)]) == 1


def test_sidecars_never_become_facts_or_engine_views(fixture, tmp_path):
    model = pack.read(fixture)
    engine = emit.compile_pack(model)
    rows = facts.load(model, fixture / "facts/data.yaml")
    metadata(fixture, {"default": DEFAULT})
    assert [p.name for p in facts.files(fixture)] == ["data.yaml"]
    assert facts.load(model, fixture / "facts/data.yaml") == rows
    assert scenarios.states(model, fixture) == [("0-data", rows)]
    assert pack.fact_files(model, fixture, "alpha", "a") == ["facts/data.yaml"]
    assert emit.compile_pack(model) == engine
    assert "generated/sources.json" not in engine
    assert main(["compile", str(fixture), str(tmp_path / "compiled")]) == 0
    assert json.loads((tmp_path / "compiled/generated/sources.json").read_text("utf-8")) == entries(fixture)
    for rel, text in engine.items():
        assert (tmp_path / "compiled" / rel).read_bytes() == text.encode("utf-8")


def test_sidecars_change_data_hash_only(fixture):
    from rezono_publisher.batch import definition_sha256, tree_sha256
    before = definition_sha256(fixture), tree_sha256(fixture)
    metadata(fixture, {"default": DEFAULT})
    after = definition_sha256(fixture), tree_sha256(fixture)
    assert before[0] == after[0]
    assert before[1] != after[1]
    metadata(fixture, {"default": DEFAULT | {"position": "different.json"}})
    assert definition_sha256(fixture) == before[0]
    assert tree_sha256(fixture) != after[1]


def test_inlined_and_inherited_rows_keep_typed_identity_and_nearest_sources(fixture):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Gamma"] = {"is_a": "Alpha"}
    schema["classes"]["Alpha"]["attributes"]["detail"] = {"range": "Detail", "inlined": True}
    schema["classes"]["Detail"] = {"attributes": {"text": {}}}
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    (fixture / "labels/nl.yaml").write_text((fixture / "labels/nl.yaml").read_text("utf-8") + "gamma: Gamma\nalpha.detail: Detail\ndetail: Detail\ndetail.text: Text\n", encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("gamma:\n  - {id: a, title: Alpha, detail: {text: Nested}}\n", encoding="utf-8")
    metadata(fixture, {"default": DEFAULT, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "position": "/parent"},
        {"of": {"kind": "gamma", "id": "a"}, "position": "/child"}]})
    result = by_row(fixture)
    assert result[("alpha", '["a"]')]["sources"][0]["position"].endswith("#/child")
    assert result[("gamma", '["a"]')]["sources"][0]["position"].endswith("#/child")
    assert result[("detail", '["a/alpha.detail"]')]["sources"][0]["position"].endswith("#/child")
    assert result[("detail__text", '["a/alpha.detail","Nested"]')]["sources"][0]["position"].endswith("#/child")
    (fixture / "facts/data.sources.yaml").unlink()
    assert all(e["sources"] == [{"kind": "pack", "name": "facts/data.yaml", "position": "2"}] for e in entries(fixture))


@pytest.mark.parametrize("cell_override", [False, True])
def test_nested_sources_inherit_the_immediate_record_not_outer_record_or_arrow_cell(fixture, cell_override):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Alpha"]["attributes"]["detail"] = {"range": "Detail", "inlined": True}
    schema["classes"]["Detail"] = {"attributes": {"sub": {"range": "Sub", "inlined": True}}}
    schema["classes"]["Sub"] = {"attributes": {"text": {}}}
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    labels = fixture / "labels/nl.yaml"
    labels.write_text(labels.read_text("utf-8") + "alpha.detail: Detail\ndetail: Detail\ndetail.sub: Sub\nsub: Sub\nsub.text: Text\n", encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, detail: {sub: {text: Nested}}}\n", encoding="utf-8")
    records = [
        {"of": {"kind": "alpha", "id": "a"}, "position": "/outer"},
        {"of": {"kind": "detail", "id": "a/alpha.detail"}, "position": "/inner", "reason": "inner.record"}]
    if cell_override:
        records += [
            {"of": {"kind": "alpha", "id": "a", "slot": "detail"}, "position": "/outer-cell"},
            {"of": {"kind": "detail", "id": "a/alpha.detail", "slot": "sub"}, "position": "/inner-cell"}]
    metadata(fixture, {"default": DEFAULT, "records": records})
    rows = by_row(fixture)
    for relation, key in [("detail", '["a/alpha.detail"]'),
                          ("sub", '["a%2Falpha.detail/detail.sub"]'),
                          ("sub__text", '["a%2Falpha.detail/detail.sub","Nested"]')]:
        assert rows[(relation, key)]["sources"] == [DEFAULT | {"position": "corpus/snapshot.json#/inner"}]
        assert rows[(relation, key)]["reason"] == "inner.record"
    assert rows[("alpha__detail", '["a","a/alpha.detail"]')]["sources"][0]["position"].endswith("#/outer-cell" if cell_override else "#/outer")
    assert rows[("detail__sub", '["a/alpha.detail","a%2Falpha.detail/detail.sub"]')]["sources"][0]["position"].endswith("#/inner-cell" if cell_override else "#/inner")


def test_a_fact_file_with_a_companion_is_never_written_without_it(fixture, tmp_path, monkeypatch):
    delta = {"format": writer.FORMAT, "changes": [{"op": "delete", "file": "facts/data.yaml", "kind": "alpha", "key": "a"}]}
    # Legacy packs retain their writer's behavior.
    changed, _ = writer.apply_delta(fixture, delta)
    assert set(changed) == {"facts/data.yaml"}
    metadata(fixture, {"default": DEFAULT})
    before = {p: p.read_bytes() for p in fixture.rglob("*") if p.is_file()}
    monkeypatch.setattr(writer, "check_work_dir", lambda _: None)
    with pytest.raises(writer.WriteError, match="its source companion must be written with it"):
        writer.write_files(fixture, changed)
    assert {p: p.read_bytes() for p in fixture.rglob("*") if p.is_file()} == before
    # The writer gives both (test_writer_sources.py); schema operations carry sources since B12 (test_operate_sources.py).
    both, _ = writer.apply_delta(fixture, delta)
    assert set(both) == {"facts/data.yaml", "facts/data.sources.yaml"} and both["facts/data.yaml"] == changed["facts/data.yaml"]


def test_a_fact_file_without_a_sidecar_is_written_as_in_a_pack_without_sidecars(fixture, monkeypatch):
    """RV-M16: the refusal is per fact file. A sidecar names only rows of its own fact file, so a change in
    another file cannot lose or stale one of its sources."""
    (fixture / "facts/other.yaml").write_text("alpha:\n  - {id: o, title: Other}\n", encoding="utf-8")
    delta = {"format": writer.FORMAT, "changes": [
        {"op": "set", "kind": "alpha", "key": "o", "slot": "title", "value": "Other (pilot)"},  # no file: located
        {"op": "insert", "file": "facts/new.yaml", "kind": "alpha", "key": "n", "values": {"title": "New"}}]}
    plain = writer.apply_delta(fixture, delta)
    metadata(fixture, {"default": DEFAULT})  # beside facts/data.yaml only
    before = entries(fixture)
    assert writer.apply_delta(fixture, delta) == plain and set(plain[0]) == {"facts/other.yaml", "facts/new.yaml"}
    monkeypatch.setattr(writer, "check_work_dir", lambda _: None)
    writer.write_files(fixture, plain[0])
    after = by_row(fixture)
    assert [e for e in entries(fixture) if e["sources"][0]["kind"] == "git"] == [e for e in before if e["sources"][0]["kind"] == "git"]
    assert after[("alpha__title", '["o","Other (pilot)"]')]["sources"] == [{"kind": "pack", "name": "facts/other.yaml", "position": "2"}]
    # The file with the sidecar changes only with it, and a row written there needs its origin (test_writer_sources.py).
    change = {"op": "insert", "file": "facts/data.yaml", "kind": "alpha", "key": "b", "values": {"title": "Beta"}}
    with pytest.raises(writer.WriteError, match=r"change 1 \(facts/data.yaml\): .* need their real origin"):
        writer.apply_delta(fixture, {"format": writer.FORMAT, "changes": [delta["changes"][0], change]})


SOURCE_FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures/source/Source"


@pytest.mark.parametrize("path", sorted(SOURCE_FIXTURES.glob("*/*.yaml")), ids=lambda p: p.name)
def test_source_runtime_matches_the_shared_contract_fixtures(path):
    value = yaml.safe_load(path.read_text("utf-8"))
    if path.parent.name == "invalid":
        with pytest.raises(facts.LoadError):
            sources.source(value, path.name)
    else:
        assert sources.source(value, path.name) == value


@pytest.mark.parametrize("field,value", [("position", " section "), ("revision", " v ")])
def test_document_conditional_patterns_preserve_legacy_compatibility(field, value):
    document = yaml.safe_load((SOURCE_FIXTURES / "valid/document-version.yaml").read_text("utf-8"))
    with pytest.raises(facts.LoadError, match=f"invalid document {field}"):
        sources.source(document | {field: value}, "document")
    assert sources.source(DEFAULT | {field: value}, "legacy") == DEFAULT | {field: value}


def test_document_fields_survive_default_and_cell_overrides_without_changing_facts(fixture):
    document = yaml.safe_load((SOURCE_FIXTURES / "valid/document-retrieved.yaml").read_text("utf-8"))
    document["ownership"] = "third_party"
    before = (fixture / "facts/data.yaml").read_bytes()
    metadata(fixture, {"default": document, "records": [{"of": {"kind": "alpha", "id": "a", "slot": "size"},
        "position": "paragraph-3", "attribution": "Example editor", "retrieved_at": "2024-02-29T12:34:56Z"}]})
    result = entries(fixture)
    cell = next(e for e in result if e["row"]["relation"] == "alpha__size")
    assert cell["sources"] == [document | {"position": "paragraph-3", "attribution": "Example editor", "retrieved_at": "2024-02-29T12:34:56Z"}]
    assert all(e["sources"][0]["url"] == document["url"] for e in result)
    assert (fixture / "facts/data.yaml").read_bytes() == before
