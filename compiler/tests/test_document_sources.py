"""Compatibility patch for the new Source fields on the pending source compiler/codec PRs."""

from pathlib import Path

import pytest
import yaml

from rede_compiler import facts, pack, sources
from test_sources import entries, fixture, metadata  # noqa: F401 (a pytest fixture)

CONTRACT_FIXTURES = Path(__file__).resolve().parents[2] / "contracts/fixtures/source/Source"
CASES = sorted(CONTRACT_FIXTURES.glob("*/*.yaml"))
DOCUMENT = {"kind": "document", "name": "Example manual", "url": "https://docs.example.invalid/manual",
            "position": "section-2", "retrieved_at": "2026-11-08T12:34:56Z", "fragment_sha256": "a" * 64,
            "licence": "LicenseRef-fixture", "attribution": "Example author", "ownership": "third_party"}


@pytest.mark.parametrize("path", CASES, ids=lambda p: p.name)
def test_runtime_source_validation_matches_the_document_contract_fixtures(path):
    value = yaml.safe_load(path.read_text("utf-8"))
    if path.parent.name == "invalid":
        with pytest.raises(facts.LoadError):
            sources.source(value, path.name)
    else:
        assert sources.source(value, path.name) == value


def test_new_fields_survive_compatible_overrides_and_exact_codec(fixture):
    metadata(fixture, {"default": DOCUMENT, "records": [{"of": {"kind": "alpha", "id": "a", "slot": "size"},
        "position": "paragraph-3", "attribution": "Example editor", "retrieved_at": "2024-02-29T12:34:56Z"}]})
    before = entries(fixture)
    text = sources.canonical_sidecar(pack.read(fixture), fixture / "facts/data.yaml", before)
    metadata(fixture, yaml.safe_load(text))
    assert entries(fixture) == before
    assert all(e["sources"][0]["url"] == DOCUMENT["url"] for e in before)
    cell = next(e for e in before if e["row"]["relation"] == "alpha__size")
    assert cell["sources"][0] == DOCUMENT | {"position": "paragraph-3", "attribution": "Example editor", "retrieved_at": "2024-02-29T12:34:56Z"}


def test_the_two_source_field_shapes_and_runtime_allowlist_do_not_drift():
    schema = sources.contract()
    assert sources.FIELDS == set(schema["classes"]["Source"]["attributes"])
    assert sources.FIELDS == set(schema["classes"]["SourceRecord"]["attributes"]) - {"of", "reason"}


@pytest.mark.parametrize("field,value", [("position", " section "), ("revision", " v ")])
def test_document_condition_patterns_match_the_contract_without_tightening_legacy_sources(field, value):
    with pytest.raises(facts.LoadError, match=f"invalid document {field}"):
        sources.source(DOCUMENT | {field: value}, "document")
    legacy = {"kind": "git", "name": "example/model", "revision": "a" * 40, "position": "file.yaml"}
    assert sources.source(legacy | {field: value}, "legacy") == legacy | {field: value}
