"""The output index of a role's standards exports, from decisions/export-output-index.md.

A one-item pack whose rules let one role read the item. The expected witnesses are the item's own rows,
written out by hand: `item` keyed by its id and `item__label` keyed by id and label.
"""

import hashlib
import json
import shutil
from pathlib import Path

import pytest
from rezono_canon import canonical_bytes
from rezono_publisher import batch, forms, publish, store

ROOT = Path(__file__).resolve().parents[3]
MINIMAL = ROOT / "compiler/tests/fixtures/minimal"
SCHEMA = """id: https://rezono.example/exported
name: exported
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
      label: {}
"""
RULES = """.decl may_read(role: symbol, kind: symbol, id: symbol)
may_read("reader", "item", x) :- item(x).
"""
EXPORTS = ["context.jsonld", "contract.odcs.yaml", "dcat.ttl", "prov.ttl", "shapes.ttl", "view.ttl"]
ITEM = {"relation": "item", "key": '["anchor"]'}
LABEL = {"relation": "item__label", "key": '["anchor","first-label"]'}


def pack(root):
    root.mkdir()
    (root / "pack.yaml").write_text('name: exported\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\n", encoding="utf-8")
    for folder, filename, content in (("schema", "exported.yaml", SCHEMA), ("rules", "access.dl", RULES),
                                      ("facts", "items.yaml", "item: [{id: anchor, label: first-label}]\n")):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return root


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_exports_carry_an_output_index(tmp_path):
    bucket = store.FileStore(tmp_path / "bucket")
    epoch = batch.epoch(pack(tmp_path / "pack"), epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[])
    manifest = publish.publish(epoch, bucket, {"reader": "may_read"}, forms=True)
    listing = json.loads(bucket.get(forms.index_key(epoch.pack, manifest["id"], "reader")))
    objects = {o["name"]: o for o in listing["objects"]}
    base = forms.prefix(epoch.pack, manifest["id"], "reader")
    data = {name: bucket.get(base + name) for name in objects}
    assert sorted(set(EXPORTS) & set(objects)) == EXPORTS  # control: all six exports were made

    assert "exports.index.json" in objects
    index = json.loads(data["exports.index.json"])
    from linkml.validator import validate
    assert [r.message for r in validate(index, str(ROOT / "contracts/output-index.yaml"), "OutputIndex").results] == []

    assert (index["pack"], index["manifest"], index["render"]["step"]) == ("exported", manifest["id"],
                                                                          "standards_exports")
    assert index["render"]["input_sha256"] == sha(canonical_bytes({
        "connectors": forms.component()["connectors"], "dataset": listing["dataset"], "manifest": manifest["id"],
        "rows": sha(data["rows.json"]), "schema": sha(data["schema.json"])}))
    files = {f["path"]: f for f in index["files"]}
    assert list(files) == EXPORTS
    assert all(files[name]["sha256"] == sha(data[name]) for name in EXPORTS)

    # Every line of an export that holds a row value names that row; no such line goes unindexed.
    for name in EXPORTS:
        lines = data[name].decode("utf-8").splitlines()
        cited = {}
        for field in files[name]["fields"]:
            if field["origin"] == "knowledge":
                cited.setdefault(field["line"], []).append(field["witness"])
            else:
                assert field["origin"] == "schema", (name, field)
                assert (field["document"]["file"], field["document"]["sha256"]) == ("schema.json",
                                                                                    sha(data["schema.json"]))
        for number, line in enumerate(lines, start=1):
            if "first-label" in line:
                assert LABEL in cited.get(number, []), (name, number, line)
            elif '"anchor"' in line or "/anchor>" in line:
                assert cited.get(number), (name, number, line)
    view = data["view.ttl"].decode("utf-8").splitlines()
    item_line = next(n for n, line in enumerate(view, start=1) if line.startswith("<") and "/Item/anchor>" in line)
    assert ITEM in [f.get("witness") for f in files["view.ttl"]["fields"] if f.get("line") == item_line]
