"""Change one input in a real pack and read the checked bytes named by its published manifest."""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from rezono_publisher import batch, publish, store


FIXTURE = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"


def published(folder, destination):
    epoch = batch.epoch(folder, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("facts", "fixture")])
    archive = store.FileStore(destination)
    manifest = publish.publish(epoch, archive, {"reader": "complete"})

    def read(entry):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        return json.loads(data)

    [bundle] = [entry for entry in manifest["compiled"] if entry["file"] == "bundle/schema-bundle.json"]
    snapshots = {entry["relation"]: read(entry) for entry in manifest["snapshots"] if entry["role"] == "reader"}
    return read(bundle), snapshots


@pytest.fixture(scope="module")
def baseline(tmp_path_factory):
    root = tmp_path_factory.mktemp("baseline")
    folder = shutil.copytree(FIXTURE, root / "pack")
    (folder / "facts").mkdir()
    (folder / "facts/rows.yaml").write_text("alpha:\n  - {id: a1, title: first}\n", encoding="utf-8")
    return folder, published(folder, root / "archive")


def change_one(baseline, tmp_path, path, old, new):
    original, before = baseline
    folder = shutil.copytree(original, tmp_path / "pack")
    target = folder / path
    source = target.read_bytes()
    assert source.count(old.encode()) == 1
    target.write_bytes(source.replace(old.encode(), new.encode()))
    return before, published(folder, tmp_path / "archive")


def test_a_changed_fact_reaches_exactly_its_published_snapshot(baseline, tmp_path):
    (old_bundle, old), (new_bundle, new) = change_one(
        baseline, tmp_path, "facts/rows.yaml", "title: first", "title: next"
    )
    assert old["alpha__title"] == [{"key": ["a1", "first"]}]
    assert new["alpha__title"] == [{"key": ["a1", "next"]}]
    assert new == old | {"alpha__title": new["alpha__title"]}
    assert old_bundle == new_bundle


def test_a_changed_translation_reaches_the_published_message_resource(baseline, tmp_path):
    old = "attribute.total = {{Elke {$kind} heeft precies één {$attribute}.}}"
    new = "attribute.total = {{Bij elke {$kind} hoort één {$attribute}.}}"
    (a, old_rows), (b, new_rows) = change_one(baseline, tmp_path, "messages/nl.mf2", old, new)
    [before] = [m["resource"] for m in a["messages"] if m["lang"] == "nl"]
    [after] = [m["resource"] for m in b["messages"] if m["lang"] == "nl"]
    assert old in before and after == before.replace(old, new)
    assert old_rows == new_rows


def test_a_changed_channel_reaches_the_published_binding(baseline, tmp_path):
    (a, old_rows), (b, new_rows) = change_one(baseline, tmp_path, "channels.yaml", "shape: rect", "shape: diamond")
    assert {k["kind"]: k["shape"] for k in a["channels"]["kinds"]} == {"alpha": "rect", "beta": "ellipse"}
    assert {k["kind"]: k["shape"] for k in b["channels"]["kinds"]} == {"alpha": "diamond", "beta": "ellipse"}
    assert old_rows == new_rows
