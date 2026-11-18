"""Exact RowRef sidecars preserve sources; the codec never rewrites fact bytes or locators."""

import json

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_compiler import facts, pack, sources, writer
from test_sources import DEFAULT, by_row, entries, fixture, metadata  # noqa: F401 (a pytest fixture)


def source(n):
    return {"kind": "person", "name": "register", "position": f"row-{n}"}


def entry(relation, key, n, **extra):
    return {"row": {"relation": relation, "key": canonical_json(key)}, "sources": [source(n)], **extra}


def save_canonical(root, rows):
    model, path = pack.read(root), root / "facts/data.yaml"
    text = sources.canonical_sidecar(model, path, rows)
    (root / "facts/data.sources.yaml").write_bytes(text.encode("utf-8"))
    return text


def test_exact_rows_override_cell_record_and_default_without_combining_values(fixture):
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: a, title: Alpha, size: [1, 2]}\n", encoding="utf-8")
    exact = entry("alpha__size", ["a", 1], 1, reason="exception.one")
    metadata(fixture, {"default": DEFAULT, "records": [
        {"of": {"kind": "alpha", "id": "a"}, "position": "/record"},
        {"of": {"kind": "alpha", "id": "a", "slot": "size"}, "position": "/cell"}], "rows": [exact]})
    rows = by_row(fixture)
    assert rows[("alpha__size", '["a","1"]')] == exact
    assert rows[("alpha__size", '["a","2"]')]["sources"] == [DEFAULT | {"position": "corpus/snapshot.json#/cell"}]
    assert rows[("alpha", '["a"]')]["sources"] == [DEFAULT | {"position": "corpus/snapshot.json#/record"}]
    assert "reason" not in rows[("alpha__size", '["a","2"]')]


def test_rows_only_roundtrip_preserves_multivalue_sources_reasons_and_canonical_union(fixture):
    facts_path = fixture / "facts/data.yaml"
    facts_path.write_text("alpha:\n  - {id: a, title: Alpha, size: [1, 2]}\n", encoding="utf-8")
    original = facts_path.read_bytes()
    expected = [entry("alpha", ["a"], 0), entry("alpha__title", ["a", "Alpha"], 0),
                entry("alpha__size", ["a", 1], 1, reason="exception.one"), entry("alpha__size", ["a", 2], 2)]
    text = save_canonical(fixture, list(reversed(expected)) + [expected[2]])
    assert json.loads(text) == {"rows": sources.collected(expected)}
    assert entries(fixture) == sources.collected(expected)
    assert sources.canonical_sidecar(pack.read(fixture), facts_path, entries(fixture)) == text
    assert facts_path.read_bytes() == original
    assert facts.load(pack.read(fixture), facts_path)["alpha__size"] == [("a", 1), ("a", 2)]


def test_parent_child_and_inlined_exact_rows_keep_distinct_sources(fixture):
    schema_path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text("utf-8"))
    schema["classes"]["Child"] = {"is_a": "Alpha"}
    schema["classes"]["Alpha"]["attributes"]["detail"] = {"range": "Detail", "inlined": True}
    schema["classes"]["Detail"] = {"attributes": {"text": {}}}
    schema_path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    labels = fixture / "labels/nl.yaml"
    labels.write_text(labels.read_text("utf-8") + "child: Child\nalpha.detail: Detail\ndetail: Detail\ndetail.text: Text\n", encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("child:\n  - {id: a, title: Alpha, detail: {text: Nested}}\n", encoding="utf-8")
    expected = [entry("alpha", ["a"], 1), entry("child", ["a"], 2), entry("alpha__title", ["a", "Alpha"], 3),
                entry("alpha__detail", ["a", "a/alpha.detail"], 4), entry("detail", ["a/alpha.detail"], 5),
                entry("detail__text", ["a/alpha.detail", "Nested"], 6, reason="nested.exception")]
    save_canonical(fixture, expected)
    assert entries(fixture) == sources.collected(expected)


def test_typed_integer_identity_uses_the_actual_canonical_row_key(fixture):
    path = fixture / "schema/minimal.yaml"
    schema = yaml.safe_load(path.read_text("utf-8"))
    schema["classes"]["Alpha"]["attributes"]["id"]["range"] = "integer"
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    (fixture / "facts/data.yaml").write_text("alpha:\n  - {id: 7, title: Seven, size: [1, 2]}\n", encoding="utf-8")
    expected = [entry("alpha", [7], 0), entry("alpha__title", [7, "Seven"], 0),
                entry("alpha__size", [7, 1], 1), entry("alpha__size", [7, 2], 2)]
    save_canonical(fixture, expected)
    assert entries(fixture) == sources.collected(expected)
    assert all(e["row"]["key"].startswith('["7"') for e in entries(fixture))


@pytest.mark.parametrize("bad", [
    {"relation": "unknown", "key": '["a"]'},
    {"relation": "alpha", "key": '["missing"]'},
    {"relation": "alpha", "key": '[ "a" ]'},
    {"relation": "alpha", "key": '["a","extra"]'},
    {"relation": "alpha__size", "key": '["a",1]'},
    {"relation": "alpha__size", "key": '["a",true]'},
    {"relation": "alpha__size", "key": '["a","not-an-integer"]'},
])
def test_exact_selectors_must_be_actual_canonical_typed_rows(fixture, bad):
    metadata(fixture, {"default": DEFAULT, "rows": [{"row": bad, "sources": [source(1)]}]})
    with pytest.raises(facts.LoadError, match="not an emitted canonical row"):
        entries(fixture)


@pytest.mark.parametrize("bad", [
    {"row": {"relation": "alpha", "key": '["a"]'}, "sources": []},
    {"row": {"relation": "alpha", "key": '["a"]'}, "sources": [source(1)], "unknown": "x"},
    {"row": {"relation": "alpha", "key": '["a"]', "unknown": "x"}, "sources": [source(1)]},
    {"row": {"relation": "alpha", "key": '["a"]'}, "sources": [{"kind": "pack", "name": "x"}]},
])
def test_exact_source_entries_fail_closed_on_invalid_shape(fixture, bad):
    metadata(fixture, {"default": DEFAULT, "rows": [bad]})
    with pytest.raises(facts.LoadError):
        entries(fixture)


def test_codec_cannot_silently_drop_a_row_or_introduce_a_source(fixture):
    original = entries(fixture)
    with pytest.raises(facts.LoadError, match="no source"):
        save_canonical(fixture, original[:-1])
    with pytest.raises(facts.LoadError, match="not an emitted canonical row"):
        save_canonical(fixture, original + [entry("alpha", ["missing"], 1)])
    assert not (fixture / "facts/data.sources.yaml").exists()


def test_exact_rows_union_sources_without_leaking_a_shadowed_cell_reason(fixture):
    first = entry("alpha__size", ["a", 1], 2, reason="exact.reason")
    metadata(fixture, {"default": DEFAULT, "records": [
        {"of": {"kind": "alpha", "id": "a", "slot": "size"}, "position": "/cell", "reason": "cell.reason"}],
        "rows": [first, first, first | {"sources": [source(1)]}]})
    row = by_row(fixture)[("alpha__size", '["a","1"]')]
    assert row["sources"] == [source(1), source(2)]
    assert row["reason"] == "exact.reason"
    metadata(fixture, {"default": DEFAULT, "rows": [first, first | {"reason": "conflict"}]})
    with pytest.raises(facts.LoadError, match="different reasons"):
        entries(fixture)


def test_implicit_file_lines_survive_materialization_without_fact_rewrite(fixture):
    path = fixture / "facts/data.yaml"
    original = path.read_bytes()
    before = entries(fixture)
    save_canonical(fixture, before)
    assert entries(fixture) == before
    assert all(e["sources"] == [{"kind": "pack", "name": "facts/data.yaml", "position": "2"}] for e in before)
    assert path.read_bytes() == original


def test_codec_can_restore_sources_after_an_external_value_roundtrip(fixture):
    path = fixture / "facts/data.yaml"
    path.write_text("alpha:\n  - {id: a, title: Alpha, size: [1, 2]}\n", encoding="utf-8")
    before_facts = path.read_bytes()
    before = [entry("alpha", ["a"], 0), entry("alpha__title", ["a", "Alpha"], 0),
              entry("alpha__size", ["a", 1], 1), entry("alpha__size", ["a", 2], 2)]
    before_sidecar = save_canonical(fixture, before)
    # A future delta writer supplies its own new source and inverse. The codec moves neither facts nor history.
    path.write_text("alpha:\n  - {id: a, title: Alpha, size: [2, 3]}\n", encoding="utf-8")
    after = before[:2] + [entry("alpha__size", ["a", 2], 4), entry("alpha__size", ["a", 3], 4)]
    save_canonical(fixture, after)
    assert entries(fixture) == sources.collected(after)
    path.write_bytes(before_facts)
    assert save_canonical(fixture, before) == before_sidecar
    assert entries(fixture) == sources.collected(before)


def test_materialised_file_positions_are_not_origins_for_the_writer(fixture):
    """The codec keeps implicit file/line sources as they are; a line the writer moves would make them false."""
    save_canonical(fixture, entries(fixture))
    assert writer.apply_delta(fixture, {"format": writer.FORMAT, "changes": []}) == ({}, {"format": writer.FORMAT, "changes": []})
    with pytest.raises(writer.WriteError, match="not a real origin"):
        writer.apply_delta(fixture, {"format": writer.FORMAT, "changes": [{"op": "delete", "kind": "alpha", "key": "a"}]})
