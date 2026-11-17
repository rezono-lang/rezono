"""MOD2 on every example golden: each kind, slot, rule, sentence and channel binding of the schema bundle has an
id and a span, and no two elements share a stable id. Light: it reads the goldens only."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
BUNDLES = sorted(ROOT.glob("**/expected/compiled/bundle/schema-bundle.json"))


@pytest.mark.xfail(strict=True, reason="generated expected/compiled goldens are not stored in git")
def test_example_bundles_are_found():
    assert BUNDLES


@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.parents[3].relative_to(ROOT).as_posix())
def test_every_element_has_an_id_and_a_span(path):
    b = json.loads(path.read_text("utf-8"))
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
