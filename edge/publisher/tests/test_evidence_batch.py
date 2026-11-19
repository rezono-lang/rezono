"""Admission in batch.epoch before the rules, from decisions/admission-transport.md sections 2 to 5.

The protected caller writes the trusted context under observations/retained/ and the submitted index under
observations/submitted/, and passes both references with the store's resolver. The receipt follows the fixture
convention of decisions/scoped-completeness.md. The expected rows are computed by hand from its body.
"""

import shutil
from pathlib import Path

import pytest
from rezono_canon import canonical_bytes, canonical_json, canonical_sha256, sha256_hex
from rezono_compiler.pack import CompileError
from rezono_publisher import batch, store
from rezono_publisher.publish import Blocked

MINIMAL = Path(__file__).resolve().parents[3] / "compiler/tests/fixtures/minimal"
RULES = """.decl verified_receipt(receipt: symbol, source: symbol, scope: symbol, cut: symbol, inventory: symbol, content: symbol)
.decl verified_member(receipt: symbol, member: symbol, part: number, value: symbol)
.decl complete(source: symbol, scope: symbol, cut: symbol, receipt: symbol)
complete(s, sc, c, r) :- verified_receipt(r, s, sc, c, _, _).
.decl covered(receipt: symbol, partition: symbol)
covered(r, p) :- verified_member(r, _, 0, p).
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
SOURCE = {"kind": "query", "name": "example-register", "revision": "snapshot-17", "position": "/enumeration"}
MEMBERS = [["partition-a"], ["partition-b"]]
CONTENT = [{"key": key, "terminal": {**SOURCE, "position": f"/partitions/{key[0]}/end"}, "rows": []}
           for key in MEMBERS]
INSTANT = "2026-01-01T00:00:00Z"


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


def pin(bucket, key, value):
    data = canonical_bytes(value)
    bucket.put_new(key, data)
    return {"file": key, "uri": bucket.uri(key), "sha256": sha256_hex(data)}


def reader(bucket):
    return lambda uri: bucket.get(uri.removeprefix(bucket.uri("")))


def body(bucket, prefix, content):
    return {
        "source": SOURCE,
        "issuer": {"id": "reader", "authorization": pin(bucket, f"{prefix}/authorization.json", {"issuer": "reader"})},
        "scope": {"definition": pin(bucket, f"{prefix}/definition.json", {"query": "partitions"}),
                  "query": "partitions", "bindings": []},
        "cut": {"frontier": {"source_id": "example-register", "position": "snapshot-17"}},
        "inventory": pin(bucket, f"{prefix}/inventory.json", MEMBERS),
        "content": pin(bucket, f"{prefix}/content.json", content),
    }


def layout(bucket, candidate_content=CONTENT):
    """The archive as the protected caller leaves it: (context, index, candidate, expected receipt row)."""
    trusted = body(bucket, "observations/retained", CONTENT)
    submitted = body(bucket, "observations/submitted", candidate_content)
    identity = canonical_sha256(["rezono.completeness-receipt/1", submitted])
    candidate = pin(bucket, "observations/submitted/receipt.json", submitted | {"id": identity})
    context = pin(bucket, "observations/retained/context.json", {"completeness": [trusted], "rounds": []})
    index = pin(bucket, "observations/submitted/index.json", {"completeness_receipts": [candidate], "rounds": []})
    expected = (identity, SOURCE["name"], canonical_sha256(trusted["scope"]), canonical_sha256(trusted["cut"]),
                trusted["inventory"]["sha256"], trusted["content"]["sha256"])
    return context, index, candidate, expected


@pytest.mark.xfail(strict=True, raises=(ImportError, CompileError, TypeError),
                   reason="M2: Waits for checker/tests/test_evidence_admission.py--test_evidence_admits_receipts_from_the_"
                          "pinned_context and compiler/tests/test_protected_admission_relations.py--test_admission_"
                          "relations_are_protected_inputs. Then give batch.epoch the keyword evidence and Epoch the "
                          "field evidence, and insert the admitted rows as base rows before the rules, as "
                          "decisions/admission-transport.md sections 2 and 5 fix. Publisher batch only.")
def test_batch_admits_evidence_before_the_rules(tmp_path):
    from rezono_checker.evidence import Evidence

    root = pack(tmp_path / "pack")
    plain = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[])
    assert (plain.rows.get("complete", []), plain.rows.get("covered", []), plain.evidence) == ([], [], None)

    bucket = store.FileStore(tmp_path / "archive")
    context, index, _, expected = layout(bucket)
    evidence = Evidence(context, index, reader(bucket))
    admitted = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[], evidence=evidence)
    identity = expected[0]
    assert admitted.evidence == evidence
    assert admitted.rows["verified_receipt"] == [expected]
    assert admitted.rows["verified_member"] == [(identity, canonical_json(key), "0", key[0]) for key in MEMBERS]
    assert admitted.rows["complete"] == [(expected[1], expected[2], expected[3], identity)]
    assert admitted.rows["covered"] == [(identity, "partition-a"), (identity, "partition-b")]

    # A rejected candidate gives no row, and nothing derived from it.
    bucket = store.FileStore(tmp_path / "mutated")
    context, index, _, _ = layout(bucket, [CONTENT[0], {**CONTENT[1], "terminal": SOURCE}])
    mutated = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                          evidence=Evidence(context, index, reader(bucket)))
    assert (mutated.rows.get("verified_receipt", []), mutated.rows.get("complete", []),
            mutated.rows.get("covered", [])) == ([], [], [])

    # A context that does not match its pin blocks the epoch.
    with pytest.raises(Blocked):
        batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                    evidence=Evidence(context | {"sha256": "0" * 64}, index, reader(bucket)))
