"""Migration acceptance for the independently authored minimal schema and Rezono fixtures."""

import json
import re

import pytest
import yaml

from rezono_compiler import emit, facts, pack
from support import text, violations
from test_rezono_module import written


@pytest.fixture(params=["schema", "module"])
def publication(tmp_path, request):
    directory = written(tmp_path, request.param)
    model = pack.read(directory)
    files = emit.compile_pack(model)
    return request.param, directory, model, files


def test_typed_facts_findings_and_presentation(publication, tmp_path):
    _, _, model, files = publication
    source = tmp_path / "observations.yaml"
    source.write_text(
        "alpha: [{id: a, title: title}]\n"
        "gamma: [{id: g, note: blue}, {id: h}]\n"
        "delta: [{id: d, gamma: g, alpha: absent, grade: third}]\n", encoding="utf-8"
    )
    rows = facts.load(model, source)
    expected = {
        "alpha": [("a",)], "alpha__title": [("a", "title")],
        "gamma": [("g",), ("h",)], "gamma__note": [("g", "blue")],
        "delta": [("d",)], "delta__gamma": [("d", "g")],
        "delta__alpha": [("d", "absent")], "delta__grade": [("d", "third")],
    }
    assert {name: sorted(values) for name, values in rows.items() if values} == expected
    assert violations(files, rows) == text({
        "gamma__note__totality": {("h",)}, "delta__alpha__reference": {("d", "absent")},
    })
    bundle = json.loads(files["bundle/schema-bundle.json"])
    sentence = next(item["sentence"] for item in bundle["arrows"] if item["id"] == "delta.gamma")
    assert sentence["message"] == "arrow.total"
    assert sentence["args"] == {"kind": "delta", "arrow": "delta.gamma", "range": "gamma"}


def source_positions(source, form):
    """Read the authored positions independent of compiler marks, scoped to their owning kind."""
    positions = {}
    if form == "schema":
        root = yaml.compose(source)
        classes = next(node for key, node in root.value if key.value == "classes")
        for kind, body in classes.value:
            positions[kind.value] = (kind.start_mark.line + 1, kind.start_mark.column + 1)
            attributes = next(node for key, node in body.value if key.value == "attributes")
            for slot, _ in attributes.value:
                if slot.value != "id":
                    positions[f"{kind.value}#{slot.value}"] = (slot.start_mark.line + 1, slot.start_mark.column + 1)
    else:
        for line, content in enumerate(source.splitlines(), 1):
            if match := re.fullmatch(r"kind (\w+) world closed", content):
                owner = match[1]
                positions[owner] = line, match.start(1) + 1
            elif match := re.fullmatch(r"  (\w+): .+", content):
                positions[f"{owner}#{match[1]}"] = line, match.start(1) + 1
    return positions


def test_source_references_belong_to_this_publication(publication):
    form, directory, _, files = publication
    path = "schema/kinds.yaml" if form == "schema" else "rezono/kinds.rezono"
    expected = source_positions((directory / path).read_text(encoding="utf-8"), form)
    assert len(expected) == 9
    bundle = json.loads(files["bundle/schema-bundle.json"])
    seen = set()
    for group in ("kinds", "arrows", "attributes"):
        for item in bundle[group]:
            module, _, local = item["stable_id"].partition("/")
            if module != "kinds":
                continue
            line, column = expected[local]
            location = {"file": path, "line": str(line), "column": str(column)}
            assert item["span"] == location
            if group != "kinds":
                assert item["sentence"]["span"] == location
            assert local not in seen
            seen.add(local)
    assert seen == expected.keys()
