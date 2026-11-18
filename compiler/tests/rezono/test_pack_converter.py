"""Check the conversion inputs before the language and publication oracles run."""

from pathlib import Path

import pytest

from scripts.convert_pack import ConversionError, candidate, rule_lines, sources


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


def test_explicit_schema_metadata_is_never_silently_discarded():
    with pytest.raises(ConversionError, match=r"schema/access\.yaml: no conversion for"):
        sources(STD, "std-access")


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
