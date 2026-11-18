"""Unknown remains explicit in an open relation (docs/vision.md, Unknown is explicit)."""

import json
import shutil
from pathlib import Path

import pytest
from rezono_compiler import emit, facts, pack
from rezono_publication import l0, publication


FIXTURE = Path(__file__).resolve().parents[2] / "compiler/tests/fixtures/minimal"


def published_cell(folder):
    model = pack.read(folder)
    bundle = json.loads(emit.compile_pack(model)["bundle/schema-bundle.json"])
    rows = facts.load(model, folder / "facts/rows.yaml")
    full = {"alpha", "alpha__title", "alpha__size"}
    form = publication.form({}, bundle, rows, full, [], [], "reader")
    l0.check_schema(form["schema"])
    l0.read_rows(form["schema"], form["rows"])
    [element] = form["rows"]
    return element["size"]


@pytest.fixture
def closed_pack(tmp_path):
    folder = shutil.copytree(FIXTURE, tmp_path / "pack")
    (folder / "facts").mkdir()
    (folder / "facts/rows.yaml").write_text("alpha:\n  - {id: a1, title: first}\n", encoding="utf-8")
    return folder


def test_full_reader_of_a_closed_optional_relation_can_establish_absence(closed_pack):
    assert published_cell(closed_pack) == {"$na": ""}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Derive the published missing-cell state from the relation world, optionality and role completeness "
    "in publication/rezono_publication/publication.py. Read docs/vision.md, Unknown is explicit."
))
def test_opening_only_the_relation_changes_the_published_missing_cell(closed_pack):
    before = published_cell(closed_pack)
    path = closed_pack / "schema/minimal.yaml"
    schema = path.read_text(encoding="utf-8")
    slot = "      size:\n        range: Count"
    assert schema.count(slot) == 1
    path.write_text(schema.replace(slot, slot + "\n        annotations:\n          world: open"), encoding="utf-8")
    after = published_cell(closed_pack)
    assert before == {"$na": ""}
    assert set(after) == {"$unknown"}
