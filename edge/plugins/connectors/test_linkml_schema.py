"""Verify standalone exports with LinkML's own reader and compare complete normalized bundles."""

import json
from pathlib import Path
import shutil

import yaml
from linkml.validator import validate
from linkml_runtime.utils.schemaview import SchemaView

import linkml_schema
from rezono_compiler import emit, pack


HERE = Path(__file__).parent
LIBRARY = HERE.parents[2] / "examples/library"
FIXTURES = HERE / "fixtures"


def exported(source, dest):
    for name, content in linkml_schema.export(source).items():
        path = dest / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return dest / (pack.read_meta(source)["name"] + ".yaml")


def compiled_bundle(source):
    return emit.compile_pack(pack.read(source))["bundle/schema-bundle.json"]


def library_semantics(text, source):
    """Compare each relocated schema span by the actual YAML key it still points to."""
    schema = "schema/library.yaml"
    tokens = {
        (str(token.start_mark.line + 1), str(token.start_mark.column + 1)): token.value
        for token in yaml.scan((source / schema).read_text(encoding="utf-8"))
        if isinstance(token, yaml.ScalarToken)
    }
    bundle = json.loads(text)
    for section in ("kinds", "arrows", "attributes", "unique_keys", "path_equations"):
        for row in bundle[section]:
            for owner in (row, row.get("sentence", {})):
                span = owner.get("span")
                if span and span["file"] == schema:
                    span["line"] = tokens[span["line"], span["column"]]
    return json.dumps(bundle, sort_keys=True)


def rebuilt(source, root, dest):
    shutil.copytree(source, dest, ignore=shutil.ignore_patterns("schema"))
    linkml_schema.write(root, dest)
    return compiled_bundle(dest)


def test_library_round_trip_preserves_the_complete_normalized_bundle(tmp_path):
    root = exported(LIBRARY, tmp_path / "one")
    view = SchemaView(str(root))
    assert view.induced_slot("reference_only", "Copy").range == "boolean"
    assert view.induced_slot("title", "Work").required
    first = tmp_path / "first"
    initial = rebuilt(LIBRARY, root, first)
    assert library_semantics(compiled_bundle(LIBRARY), LIBRARY) == library_semantics(initial, first)
    root = exported(first, tmp_path / "two")
    second = rebuilt(first, root, tmp_path / "second")
    assert initial == second


def test_standard_fixture_import_preserves_required_slot_and_enum_order(tmp_path):
    source = FIXTURES / "linkml-standard/linkml/index.yaml"
    target = tmp_path / "pack"
    shutil.copytree(FIXTURES / "linkml-standard/pack", target)
    linkml_schema.write(source, target)
    exported_root = exported(target, tmp_path / "export")
    good = {"id": "alpha", "label": "Sample", "status": "draft"}
    for path in (source, exported_root):
        view = SchemaView(str(path))
        assert list(view.get_enum("Status").permissible_values) == ["draft", "final", "retired"]
        assert view.induced_slot("label", "Record").required
        assert validate(good, str(path), "Record").results == []
        assert validate({"id": "alpha", "status": "draft"}, str(path), "Record").results
