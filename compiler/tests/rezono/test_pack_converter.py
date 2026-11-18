"""Check the conversion inputs before the language and publication oracles run."""

from pathlib import Path
import shutil

import pytest
import yaml

from rezono_compiler import modules
from scripts.convert_pack import ConversionError, candidate, compare_imported, rule_lines, sources


REPO = Path(__file__).resolve().parents[3]
STD = REPO / "packs/std-access"


def schema(directory: Path) -> Path:
    path = directory / "schema/example.yaml"
    path.parent.mkdir(parents=True)
    path.write_text(
        "id: https://rezono.org/rezono/sample/example\n"
        "name: example\n"
        "imports: [linkml:types]\n"
        "annotations: {layer: facts}\n"
        "enums:\n"
        "  State:\n"
        "    permissible_values: {pending: {}, ready: {}}\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      state: {range: State, required: true}\n"
        "      date: {range: date}\n",
        encoding="utf-8",
    )
    return path


def test_conversion_keeps_schema_and_rule_module_identity(tmp_path):
    schema(tmp_path)
    rules = tmp_path / "rules/example.dl"
    rules.parent.mkdir()
    rules.write_text(".decl seen(item: symbol)\nseen(x) :- item(x).\n.output seen\n", encoding="utf-8")
    plan = sources(tmp_path, "sample")
    assert list(plan) == ["example"]
    assert plan["example"].layer == "facts"
    assert plan["example"].lines == [
        "enum State world closed = pending | ready",
        "",
        "kind Item world closed",
        "  state: State",
        "  date: Date?",
        "",
        "rules example",
        "  | .decl seen(item: symbol)",
        "  | seen(x) :- item(x).",
        "  | .output seen",
        "",
    ]


def test_conversion_preserves_the_standard_access_declaration():
    original = (STD / "rules/access.dl").read_text(encoding="utf-8")
    header, *encoded, last = rule_lines(STD / "rules/access.dl")
    assert header == "rules access"
    assert last == ""
    assert all(line.startswith("  | ") for line in encoded)
    assert "\n".join(line[4:] for line in encoded) + "\n" == original
    assert "  | // @extend" in encoded


def test_conversion_renders_the_metadata_of_the_standard_access_pack():
    access = sources(STD, "std-access")["access"]
    assert access.lines[:7] == [
        "schema std_access",
        '  iri "https://rezono.example/std-access/access"',
        "  language en",
        '  prefix linkml = "https://w3id.org/linkml/"',
        '  prefix rdfs = "http://www.w3.org/2000/01/rdf-schema#"',
        '  import "linkml:types"',
        "  default range Text",
    ]
    title = access.lines.index("  title: Text")
    assert access.lines[title + 1] == '    iri "rdfs:label"'
    assert "  capability: Capability*" in access.lines
    member = access.lines.index("  value read")
    assert access.lines[member + 1] == "    description \"reads what the pack's read rules give this capability\""
    assert "  | // @extend" in access.lines


def test_unrepresented_mappings_are_never_silently_discarded():
    with pytest.raises(ConversionError, match=r"Constituent.part_of: no conversion for broad_mappings, close_mappings"):
        sources(REPO / "packs/std-part", "std-part")


def test_failed_reader_does_not_leave_a_candidate(tmp_path):
    original = tmp_path / "sample"
    authored = schema(original)
    meta = original / "pack.yaml"
    meta.write_text("name: sample\nversion: '0'\ndefault_language: en\nimports: []\n", encoding="utf-8")
    before = authored.read_bytes()
    destination = tmp_path / "trial"
    with pytest.raises(FileNotFoundError):
        candidate(original, destination, str(tmp_path / "node-not-installed"))
    assert authored.read_bytes() == before
    assert not destination.exists()
    assert set(tmp_path.iterdir()) == {original}


def test_imported_standard_pack_preserves_named_title_through_its_consumer(tmp_path):
    original = Path(shutil.copytree(STD, tmp_path / "std-access"))
    trial = Path(shutil.copytree(STD, tmp_path / "trial"))
    consumer = Path(shutil.copytree(REPO / "compiler/tests/fixtures/minimal", tmp_path / "consumer"))
    metadata = consumer / "pack.yaml"
    meta = yaml.safe_load(metadata.read_bytes())
    meta["imports"] = [{"name": "std-access", "path": "../std-access", "sha256": modules.pack_hash(original)}]
    contents = yaml.safe_dump(meta).encode("utf-8")
    metadata.write_bytes(contents)
    compare_imported(consumer, original, trial, "std-access")

    schema_file = trial / "schema/access.yaml"
    schema = yaml.safe_load(schema_file.read_bytes())
    del schema["classes"]["Role"]["attributes"]["title"]["slot_uri"]
    schema_file.write_bytes(yaml.safe_dump(schema).encode("utf-8"))
    with pytest.raises(ConversionError, match="changed the typed schema"):
        compare_imported(consumer, original, trial, "std-access")
    assert metadata.read_bytes() == contents
    assert set(tmp_path.iterdir()) == {original, trial, consumer}
