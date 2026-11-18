"""Check Elm's actual publication before and after a read-grant change."""

import json
import shutil

import yaml
from rezono_compiler import rules
from rezono_publisher import batch, publish, store

from case_support import ROOT, imported
from examples.platform.test_tenant_publication_proof import graph, leaves


CAPACITY = ("tenant_capacity_fits", ("elm", "elm-request", "elm-quota"))
PEER_CAPACITY = ("tenant_capacity_fits", ("reed", "reed-request", "reed-quota"))
REQUEST = ("request", ("elm-request",))
QUOTA = ("quota", ("elm-quota",))
OTHER_GRANT = ("quota_read_grant", ("reed-quota-read",))
ROLES = {"checker": "complete", "elm": "may_read", "reed": "may_read"}


def copy_pack(directory):
    target = directory / "examples" / "platform"
    shutil.copytree(ROOT, target)
    shutil.copytree(ROOT.parents[1] / "packs", directory / "packs")
    return target


def checked_publication(pack, bucket, number):
    epoch = batch.epoch(pack, epoch=number, knowledge_time=f"2026-01-{number:02d}T00:00:00Z",
                        sources=[("rules", "access-test")])
    manifest = publish.publish(epoch, bucket, ROLES)
    return epoch, manifest


def role_evidence(bucket, publication, role):
    epoch, manifest = publication
    objects = publish.role_objects(bucket, epoch.pack, manifest["id"], role)
    rows = {(path.removeprefix("relations/").removesuffix(".json"), tuple(item["key"]))
            for path, key in objects.items() if path.startswith("relations/")
            for item in json.loads(bucket.get(key))}
    full = {s["relation"] for s in manifest["snapshots"] if s["role"] == role and s["full"]}
    document = json.loads(bucket.get(objects["witnesses.json"]))
    return rows, graph(rows, document, full, rules.load(json.loads(epoch.rules)))


def test_standard_access(tmp_path):
    imported("std-access")
    pack = copy_pack(tmp_path / "inputs")
    bucket = store.FileStore(tmp_path / "published")
    baseline = checked_publication(pack, bucket, 1)
    visible, proofs = role_evidence(bucket, baseline, "elm")
    _, complete = role_evidence(bucket, baseline, "checker")
    assert {REQUEST, QUOTA, CAPACITY} <= visible
    assert {("request", ("reed-request",)), ("quota", ("reed-quota",)), OTHER_GRANT}.isdisjoint(visible)
    assert CAPACITY in proofs and CAPACITY in complete
    grounds = leaves(proofs, CAPACITY)
    assert grounds == leaves(complete, CAPACITY)
    assert grounds <= visible
    assert {
        ("request__cores", ("elm-request", "2")),
        ("quota__cores", ("elm-quota", "4")),
        ("request_read_grant__request", ("elm-request-read", "elm-request")),
        ("quota_read_grant__quota", ("elm-quota-read", "elm-quota")),
        ("role__capability", ("elm", "read")),
    } <= grounds

    source = pack / "facts" / "tenant-access.yaml"
    facts = yaml.safe_load(source.read_text(encoding="utf-8"))
    grant = {"id": "elm-quota-read", "reader": "elm", "quota": "elm-quota"}
    facts["quota_read_grant"].remove(grant)
    source.write_text(yaml.safe_dump(facts), encoding="utf-8")
    revoked = checked_publication(pack, bucket, 2)
    visible, proofs = role_evidence(bucket, revoked, "elm")
    all_rows, complete = role_evidence(bucket, revoked, "checker")
    peer_rows, peer_proofs = role_evidence(bucket, revoked, "reed")
    assert REQUEST in visible and QUOTA in all_rows
    assert ("may_read", ("elm", "request", "elm-request")) in all_rows
    assert ("may_read", ("elm", "quota", "elm-quota")) not in all_rows
    assert {QUOTA, CAPACITY}.isdisjoint(visible)
    assert CAPACITY not in proofs and CAPACITY not in all_rows and CAPACITY not in complete
    assert PEER_CAPACITY in peer_rows and PEER_CAPACITY in peer_proofs


def test_standard_access_withholds_a_conclusion_with_an_unreadable_ground(tmp_path):
    pack = copy_pack(tmp_path / "inputs")
    rule = pack / "rules" / "tenant_access.dl"
    text = rule.read_text(encoding="utf-8")
    head = "tenant_capacity_fits(r, request, quota) :- "
    assert text.count(head) == 1
    # Both Elm grants still hold. The extra premise is a different reader's grant.
    rule.write_text(text.replace(head, head + 'quota_read_grant("reed-quota-read"), '), encoding="utf-8")

    bucket = store.FileStore(tmp_path / "published")
    publication = checked_publication(pack, bucket, 1)
    visible, proofs = role_evidence(bucket, publication, "elm")
    all_rows, complete = role_evidence(bucket, publication, "checker")
    assert {REQUEST, QUOTA} <= visible
    assert CAPACITY in all_rows and CAPACITY in complete
    assert OTHER_GRANT in leaves(complete, CAPACITY)
    assert {OTHER_GRANT, CAPACITY}.isdisjoint(visible) and CAPACITY not in proofs
