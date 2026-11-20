"""Build a real, pinned two-tenant publication for local reader acceptance tests."""

from hashlib import sha256
import json
from pathlib import Path

import pytest
import yaml

from examples.platform.test_tenant_publication_proof import leaves
from rezono_compiler.modules import pack_hash
from rezono_publisher import batch, pointers, publish, store
from test_standard_access import copy_pack, role_evidence


ROLES = {"elm": "may_read", "reed": "may_read"}
ABSENT_REQUEST = "unused-request"
# The import pins the standard pack's bytes at this revision, computed rather than copied, so a change to
# packs/std-explain does not also have to edit this test.
STD_EXPLAIN = {
    "name": "std-explain",
    "path": "../../packs/std-explain",
    "sha256": pack_hash(Path(__file__).resolve().parents[3] / "packs" / "std-explain"),
}


def build_role_publication(directory):
    """Return the compiled epoch, local store and manifest from ordinary publication."""
    pack = copy_pack(directory / "inputs")
    metadata = pack / "pack.yaml"
    authored = yaml.safe_load(metadata.read_text(encoding="utf-8"))
    # The platform uses theory-specific questions. Add the generic reader terms through their actual pack.
    if not any(entry["name"] == STD_EXPLAIN["name"] for entry in authored["imports"]):
        authored["imports"].append(STD_EXPLAIN)
        metadata.write_text(yaml.safe_dump(authored, sort_keys=False), encoding="utf-8")

    # A second independently granted request per tenant makes a real two-page language answer possible.
    extra = {
        "request": [
            {"id": "elm-second-request", "owner": "elm", "cores": 3},
            {"id": "reed-second-request", "owner": "reed", "cores": 1},
        ],
        "request_read_grant": [
            {"id": "elm-second-read", "reader": "elm", "request": "elm-second-request"},
            {"id": "reed-second-read", "reader": "reed", "request": "reed-second-request"},
        ],
    }
    source = pack / "facts" / "client-requests.yaml"
    source.write_text(yaml.safe_dump(extra), encoding="utf-8")
    epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                        sources=[("rules", "role-publication-fixture")])
    bucket = store.FileStore(directory / "publication")
    manifest = publish.publish(epoch, bucket, ROLES)
    return epoch, bucket, manifest


def named_bytes(bucket, entry):
    prefix = bucket.uri("")
    assert entry["uri"].startswith(prefix)
    data = bucket.get(entry["uri"].removeprefix(prefix))
    assert data is not None and sha256(data).hexdigest() == entry["sha256"]
    return data


def test_role_publication_fixture(tmp_path):
    epoch, bucket, manifest = build_role_publication(tmp_path)
    assert manifest["id"] == "m-1" and publish.newest_main(bucket, epoch.pack) == manifest
    head_key, = bucket.list(f"{epoch.pack}/heads/")
    assert head_key == pointers.head_key(epoch.pack, 1)
    manifest_key = f"{epoch.pack}/manifests/m-1.json"
    manifest_sha = sha256(bucket.get(manifest_key)).hexdigest()
    assert json.loads(bucket.get(head_key)) == {
        "format": pointers.HEAD, "epoch": 1, "manifest": "m-1", "sha256": manifest_sha,
    }
    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])

    bundle_ref, = [entry for entry in manifest["compiled"] if entry["file"] == "bundle/schema-bundle.json"]
    bundle = json.loads(named_bytes(bucket, bundle_ref))
    assert {question["term"] for question in bundle["questions"]} >= {"grounds", "reach"}
    assert {entry["role"] for entry in manifest["snapshots"]} == ROLES.keys()
    assert {entry["role"] for entry in manifest["witnesses"]} == ROLES.keys()

    expected = {
        "elm": {"elm-request": "2", "elm-second-request": "3"},
        "reed": {"reed-request": "2", "reed-second-request": "1"},
    }
    real_requests = {key for (key,) in epoch.rows["request"]}
    assert expected["elm"].keys() | expected["reed"].keys() <= real_requests
    assert ABSENT_REQUEST not in real_requests

    request_hashes = set()
    for role, peer in (("elm", "reed"), ("reed", "elm")):
        rows, proof = role_evidence(bucket, (epoch, manifest), role)
        assert {key[0] for relation, key in rows if relation == "request"} == expected[role].keys()
        assert {key for relation, key in rows if relation == "request__cores"} == set(expected[role].items())
        request_ref, = [entry for entry in manifest["snapshots"]
                        if entry["role"] == role and entry["relation"] == "request"]
        assert {tuple(item["key"]) for item in json.loads(named_bytes(bucket, request_ref))} == {
            (key,) for key in expected[role]
        }
        request_hashes.add(request_ref["sha256"])
        for name in ("snapshots", "witnesses", "fact_sources"):
            foreign = (*expected[peer], f"{peer}-quota")
            for entry in (item for item in manifest[name] if item["role"] == role):
                body = named_bytes(bucket, entry)
                assert all(key.encode() not in body for key in foreign)
        for key, value in expected[role].items():
            conclusion = ("tenant_capacity_fits", (role, key, f"{role}-quota"))
            assert conclusion in rows and conclusion in proof
            assert {("request__cores", (key, value)), ("quota__cores", (f"{role}-quota", "4"))} <= leaves(proof, conclusion)
    assert len(request_hashes) == 2

    first = {key: bucket.get(key) for key in bucket.list("")}
    second = store.FileStore(tmp_path / "second-publication")
    assert publish.publish(epoch, second, ROLES) == manifest
    assert {key: second.get(key) for key in second.list("")} == first
    bucket.put_new(manifest_key, first[manifest_key])
    with pytest.raises(store.Conflict):
        bucket.put_new(manifest_key, b"{}")
    assert {key: bucket.get(key) for key in bucket.list("")} == first
