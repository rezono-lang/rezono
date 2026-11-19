"""Who reads the protected admission inputs, from decisions/admission-transport.md section 6.

The protected relations expose the trusted inventory of an admitted receipt, member keys included. Until a
decision gives them a read rule or element columns, only the complete side reads them: a filtered role gets
no row of them, and no derived conclusion that rests on them. The archive layout and the pack come from
test_evidence_batch.
"""

import json

import pytest
from rezono_publisher import access, batch, publish, store
from test_evidence_batch import INSTANT, layout, pack, reader

ROLES = {"checker": "complete", "reader": "may_read"}


def epoch_with_evidence(tmp_path):
    from rezono_checker.evidence import Evidence

    root = pack(tmp_path / "pack")
    # The members are items of the pack; the reader is granted none of them.
    (root / "facts/items.yaml").write_text("item: [{id: partition-a}, {id: partition-b}]\n", encoding="utf-8")
    bucket = store.FileStore(tmp_path / "archive")
    context, index, _, _ = layout(bucket)
    return batch.epoch(root, epoch=1, knowledge_time=INSTANT, sources=[],
                       evidence=Evidence(context, index, reader(bucket))), bucket


def role_rows(bucket, epoch, manifest, role):
    objects = publish.role_objects(bucket, epoch.pack, manifest["id"], role)
    return {name.removeprefix("relations/").removesuffix(".json"): json.loads(bucket.get(key))
            for name, key in objects.items() if name.startswith("relations/")}


def test_a_role_without_rights_reads_no_admitted_evidence(tmp_path):
    epoch, bucket = epoch_with_evidence(tmp_path)
    manifest = publish.publish(epoch, bucket, ROLES)

    complete = role_rows(bucket, epoch, manifest, "checker")
    assert len(complete["verified_member"]) == 2 and len(complete["covered"]) == 2

    rows = role_rows(bucket, epoch, manifest, "reader")
    assert rows.get("item", []) == []
    for relation in ("verified_receipt", "verified_member", "covered", "complete"):
        assert rows.get(relation, []) == [], relation


def test_the_checker_refuses_a_role_that_reads_admitted_evidence(tmp_path, monkeypatch):
    # The publisher's filter without the withholding: the checker decides the role's scope itself, from the rule
    # IR and its own list of protected relations, and blocks the publication.
    monkeypatch.setattr(access.Scope, "_withheld_admission", staticmethod(lambda rules: frozenset()))
    epoch, bucket = epoch_with_evidence(tmp_path)
    with pytest.raises(publish.Blocked, match="not_readable"):
        publish.publish(epoch, bucket, ROLES)
