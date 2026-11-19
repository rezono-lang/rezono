"""Admitted completeness receipts on the publication path, from decisions/admission-transport.md.

The caller passes the pinned trusted context and the submitted index as one `Evidence`; only admitted
candidates fill the protected input `verified_receipt`; the complete manifest lists the candidates; the
checker admits again and refuses a protected row that admission did not produce. The trusted context is
never published. The archive layout, the receipt and the expected conclusion come from
test_evidence_batch, written by hand.
"""

import dataclasses
import json

import pytest
from rezono_compiler.pack import CompileError
from rezono_publisher import batch, publish, store
from test_evidence_batch import CONTENT, INSTANT, SOURCE, layout, pack, reader

ROLES = {"checker": "complete", "reader": "may_read"}


def published(epoch, bucket):
    manifest = publish.publish(epoch, bucket, ROLES)
    assert {"name": publish.PROOFS, "status": "green", "violations": 0} in manifest["checks"]
    rows = {name: json.loads(bucket.get(key)) for name, key in
            publish.role_objects(bucket, epoch.pack, manifest["id"], "checker").items()}
    return manifest, rows.get("relations/complete.json", [])


@pytest.mark.xfail(strict=True, raises=(ImportError, CompileError, TypeError),
                   reason="Waits for edge/publisher/tests/test_evidence_batch.py--test_batch_admits_evidence_before_"
                          "the_rules. Then pass Epoch.evidence from publish.verify to check_epoch on the complete side, "
                          "list completeness_receipts and rounds in the complete manifest from publish.plan, and keep "
                          "the trusted context out of every manifest, as decisions/admission-transport.md sections 2 "
                          "and 5 fix.")
def test_publisher_admits_receipts_only_with_a_trusted_context(tmp_path):
    from rezono_checker.evidence import Evidence

    root = pack(tmp_path / "pack")
    control = store.FileStore(tmp_path / "control")
    manifest, rows = published(batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[]), control)
    assert rows == [] and not manifest.get("completeness_receipts")

    bucket = store.FileStore(tmp_path / "admitted")
    context, index, candidate, expected = layout(bucket)
    epoch = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                        evidence=Evidence(context, index, reader(bucket)))
    manifest, rows = published(epoch, bucket)
    assert rows == [{"key": [expected[1], expected[2], expected[3], expected[0]]}]
    assert (manifest["completeness_receipts"], manifest.get("rounds", [])) == ([candidate], [])
    assert context["sha256"] not in json.dumps(manifest)

    # A mutated candidate: still listed, a warning only, no conclusion.
    bucket = store.FileStore(tmp_path / "mutated")
    context, index, candidate, _ = layout(bucket, [CONTENT[0], {**CONTENT[1], "terminal": SOURCE}])
    epoch = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                        evidence=Evidence(context, index, reader(bucket)))
    manifest, rows = published(epoch, bucket)
    assert rows == [] and manifest["completeness_receipts"] == [candidate]

    # A protected row the checker cannot admit again blocks the publication.
    bucket = store.FileStore(tmp_path / "unadmitted")
    context, index, _, _ = layout(bucket)
    epoch = batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                        evidence=Evidence(context, index, reader(bucket)))
    with pytest.raises(publish.Blocked, match="receipt_not_admitted"):
        publish.publish(dataclasses.replace(epoch, evidence=Evidence(context, None, reader(bucket))), bucket, ROLES)
