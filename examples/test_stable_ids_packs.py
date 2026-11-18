"""Stable identifiers and source spans in the compiler output for every example pack."""

import json
from pathlib import Path

import pytest

from rezono_compiler import emit, pack

ROOT = Path(__file__).resolve().parent
PACKS = sorted(path.parent for path in ROOT.rglob("pack.yaml") if "expected" not in path.relative_to(ROOT).parts)


def bundle(folder):
    return json.loads(emit.compile_pack(pack.read(folder))["bundle/schema-bundle.json"])


def test_library_identifiers_follow_the_declared_module_classes_and_slots():
    # schema/library.yaml declares the classes Copy and Work and these two attributes.
    # Stable IDs compose the module and original class name, then the slot after '#'.
    compiled = bundle(ROOT / "library")
    kinds = {item["id"]: item["stable_id"] for item in compiled["kinds"]}
    attributes = {(item["kind"], item["name"]): item["stable_id"] for item in compiled["attributes"]}
    assert (kinds["copy"], kinds["work"]) == ("library/Copy", "library/Work")
    assert attributes["copy", "reference_only"] == "library/Copy#reference_only"
    assert attributes["work", "title"] == "library/Work#title"


@pytest.mark.parametrize("folder", PACKS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_element_has_an_id_and_a_span(folder):
    b = bundle(folder)
    elements = [*b["kinds"], *b.get("arrows", []), *b.get("attributes", []), *b.get("rules", [])]
    sentences = [x["sentence"] for x in [*elements, *b.get("unique_keys", []), *b.get("path_equations", [])]
                 if "sentence" in x]
    for x in elements:
        assert x.get("stable_id") and x.get("span"), x["id"]
    for s in sentences:
        assert s.get("id", "").startswith("sentence:") and s.get("span"), s
    sources = b["channels"].get("sources", [])
    assert {s["id"] for s in sources} >= {f"kinds/{k['kind']}" for k in b["channels"].get("kinds", [])}
    assert all(s["span"]["line"] != "0" for s in sources)
    stable = [x["stable_id"] for x in elements]
    assert len(stable) == len(set(stable))
    assert len({s["id"] for s in sentences}) == len(sentences)
