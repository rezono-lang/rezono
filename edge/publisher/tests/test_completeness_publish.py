"""Candidate completeness receipts and their trusted context at the batch and publisher boundary.

decisions/scoped-completeness.md, admission and replay transport: the caller passes candidate
references and trusted contexts separately; only admitted candidates fill the protected input
`verified_receipt`; the complete manifest lists the candidates and the trusted context is never
published. The receipt, its inventory and the expected conclusion are written by hand here.
"""

import json
import shutil
from pathlib import Path

import pytest
from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from rezono_compiler.pack import CompileError
from rezono_publisher import batch, publish, store

MINIMAL = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
RULES = """.decl verified_receipt(receipt: symbol, source: symbol, scope: symbol, cut: symbol, inventory: symbol, content: symbol)
.decl complete(source: symbol, scope: symbol, cut: symbol, receipt: symbol)
complete(s, sc, c, r) :- verified_receipt(r, s, sc, c, _, _).
"""
SCHEMA = """id: https://rezono.example/receipts
name: receipts
in_language: en
imports: [linkml:types]
default_range: string
annotations: {layer: facts}
classes:
  Item:
    attributes:
      id: {identifier: true}
"""
ROLES = {"checker": "complete", "reader": "may_read"}
SOURCE = {"kind": "query", "name": "example-register", "revision": "snapshot-17", "position": "/enumeration"}
CONTENT = [{"key": ["partition-a"], "terminal": {**SOURCE, "position": "/partitions/a/end"}, "rows": []}]


def pack(root):
    root.mkdir()
    (root / "pack.yaml").write_text('name: receipts\nversion: "1"\ndefault_language: nl\n', encoding="utf-8")
    shutil.copytree(MINIMAL / "messages", root / "messages")
    (root / "channels.yaml").write_text("kinds: [{kind: item, shape: rect}]\n", encoding="utf-8")
    (root / "labels").mkdir()
    (root / "labels/nl.yaml").write_text("item: Item\n", encoding="utf-8")
    for folder, filename, content in (("schema", "receipts.yaml", SCHEMA), ("rules", "complete.dl", RULES),
                                      ("facts", "items.yaml", "item: [{id: anchor}]\n")):
        (root / folder).mkdir()
        (root / folder / filename).write_text(content, encoding="utf-8")
    return root


def pin(bucket, name, value):
    data = canonical_bytes(value)
    key = f"archive/{sha256_hex(data)}.json"
    bucket.put_new(key, data)
    return {"file": name, "uri": bucket.uri(key), "sha256": sha256_hex(data)}


def receipt(bucket):
    definition = pin(bucket, "scope-definition.json", {"query": "partitions"})
    context = {
        "source": SOURCE,
        "issuer": {"id": "reader", "authorization": pin(bucket, "authorized-issuer.json", {"issuer": "reader"})},
        "scope": {"definition": definition, "query": "partitions", "bindings": []},
        "cut": {"frontier": {"source_id": "example-register", "position": "snapshot-17"}},
        "inventory": pin(bucket, "expected-members.json", [["partition-a"]]),
        "content": pin(bucket, "captured-content.json", CONTENT),
    }
    identity = canonical_sha256(["rezono.completeness-receipt/1", context])
    reference = pin(bucket, "receipt.json", context | {"id": identity})
    expected = [SOURCE["name"], canonical_sha256(context["scope"]), canonical_sha256(context["cut"]), identity]
    return reference, context, expected


def published(root, bucket, **admission):
    epoch = batch.epoch(root, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[], **admission)
    manifest = publish.publish(epoch, bucket, ROLES)
    assert {"name": publish.PROOFS, "status": "green", "violations": 0} in manifest["checks"]
    rows = {name: json.loads(bucket.get(key)) for name, key in
            publish.role_objects(bucket, epoch.pack, manifest["id"], "checker").items()}
    return manifest, rows.get("relations/complete.json", [])


@pytest.mark.xfail(strict=True, raises=(CompileError, TypeError),
                   reason="Waits for compiler/tests/test_verified_receipt_input.py--test_verified_receipt_is_a_protected_input. "
                          "Then add completeness_receipts, completeness_authority and archive to batch.epoch, fill "
                          "verified_receipt only from rezono_checker.completeness.admit, list the candidates in the "
                          "complete manifest and pass the trusted contexts to check_epoch, as "
                          "decisions/scoped-completeness.md (admission and replay transport) fixes.")
def test_publisher_admits_receipts_only_with_a_trusted_context(tmp_path):
    root = pack(tmp_path / "pack")
    manifest, rows = published(root, store.FileStore(tmp_path / "control"))
    assert rows == [] and not manifest.get("completeness_receipts")

    bucket = store.FileStore(tmp_path / "admitted")
    reference, context, expected = receipt(bucket)
    manifest, rows = published(root, bucket, completeness_receipts=[reference], completeness_authority=[context],
                               archive=bucket)
    assert rows == [{"key": expected}]
    assert manifest["completeness_receipts"] == [reference]

    # The same candidate without a trusted context: still listed, coverage unknown, no conclusion.
    bucket = store.FileStore(tmp_path / "untrusted")
    reference, _, _ = receipt(bucket)
    manifest, rows = published(root, bucket, completeness_receipts=[reference], completeness_authority=[],
                               archive=bucket)
    assert rows == []
    assert manifest["completeness_receipts"] == [reference]
