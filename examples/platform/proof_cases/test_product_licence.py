"""Read licence information and its evidence from the checked platform publication."""

import hashlib
import json
import shutil

import pytest
import yaml

from case_support import ROOT
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of


def publication(pack, destination):
    epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                        sources=[("rules", "licence-example")])
    bucket = store.FileStore(destination)
    published = publish.publish(epoch, bucket, {"checker": "complete", "platform-catalogue": "may_read"})
    manifest = json.loads(bucket.get(f"{epoch.pack}/manifests/{published['id']}.json"))
    return bucket, manifest


def referenced_json(bucket, entry):
    data = bucket.get(key_of(entry["uri"]))
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    return json.loads(data)


def snapshot(publication, relation, role="platform-catalogue"):
    bucket, manifest = publication
    entry, = [s for s in manifest["snapshots"] if s["role"] == role and s["relation"] == relation]
    return {tuple(item["key"]) for item in referenced_json(bucket, entry)}


def copy_platform(tmp_path):
    pack = tmp_path / "examples" / "platform"
    shutil.copytree(ROOT, pack)
    shutil.copytree(ROOT.parents[1] / "packs", tmp_path / "packs")
    return pack


def test_product_licence_follows_the_selected_release(tmp_path):
    pack = copy_platform(tmp_path)
    original = publication(pack, tmp_path / "original")
    rows = snapshot(original, "component_product_licence")
    states = snapshot(original, "component_licence_state")
    assert rows == snapshot(original, "component_product_licence", "checker")
    assert states == snapshot(original, "component_licence_state", "checker")
    assert not snapshot(original, "quota")
    assert {(s, p) for s, p, _ in states} == snapshot(original, "service__product")

    pg16 = ("db-git", "postgresql", "16.0", "example-of-selected-series", "project-source", "PostgreSQL",
            "https://raw.githubusercontent.com/postgres/postgres/REL_16_0/COPYRIGHT",
            "1a7d13c3ab31961b91ba256f77d6e82e0b54bf992253060fe93bdb5466df416a")
    assert pg16 in rows
    assert any(row[:4] == ("db-idp", "postgresql", "17.0", "example-of-selected-series") for row in rows)
    assert ("postgresql-16", "16") in snapshot(original, "release__series")
    assert ("postgresql-16.0", "16") in snapshot(original, "vendor_licence_notice__series")
    assert any(row[:6] == ("idp", "keycloak", "26.0.0", "exact-scenario-release", "project-source", "Apache-2.0")
               for row in rows)
    assert any(row[:6] == ("cp", "kube-control", "1.32.13", "exact-scenario-release", "project-source", "Apache-2.0")
               for row in rows)
    assert any(row[:5] == ("store", "ceph", "19.2.0", "reference-source-release", "per-path-notices")
               for row in rows)
    bucket, manifest = original
    entry, = [s for s in manifest["fact_sources"] if s["role"] == "platform-catalogue"]
    sources = referenced_json(bucket, entry)
    notice, = [e for e in sources if e["row"]["relation"] == "vendor_licence_notice__declaration"
               and json.loads(e["row"]["key"]) == ["postgresql-16.0", "PostgreSQL"]]
    evidence, = notice["sources"]
    assert (evidence["kind"], evidence["revision"], evidence["url"]) == ("tool", pg16[2], pg16[-2])
    assert evidence["fragment_sha256"] == "fd4179f03d1929bc5f2a2899da10dc86ac9df0407763d3d629b200cdde204903"

    # A valid notice identifier for the wrong product cannot license the selected PostgreSQL release.
    path = pack / "facts" / "licence-bindings.yaml"
    bindings = yaml.safe_load(path.read_text(encoding="utf-8"))
    old, = [b for b in bindings["licence_release_binding"] if b["selected_release"] == "postgresql-16"]
    old["notice"] = "keycloak-26.0.0"
    path.write_text(yaml.safe_dump(bindings, sort_keys=False), encoding="utf-8")
    changed = publication(pack, tmp_path / "changed")
    assert snapshot(changed, "component_product_licence") == rows - {pg16}
    assert snapshot(changed, "component_licence_state") == (
        states - {("db-git", "postgresql", "example-of-selected-series")}
        | {("db-git", "postgresql", "unknown-selected-release")})
    assert snapshot(changed, "unverified_supply", "checker") == snapshot(original, "unverified_supply", "checker")


@pytest.mark.parametrize(
    "file, kind, entity, slot, value, service, product",
    [
        pytest.param("licence-bindings", "licence_release_binding", "bind-postgresql-16",
                     "notice", "postgresql-17.0", "db-git", "postgresql", id="wrong-series"),
        pytest.param("core", "release", "postgresql-16",
                     "series", None, "db-git", "postgresql", id="missing-selected-series"),
        pytest.param("licence-postgresql", "vendor_licence_notice", "postgresql-16.0",
                     "series", None, "db-git", "postgresql", id="missing-source-series"),
        pytest.param("core", "release", "keycloak-26",
                     "version", "25.0.0", "idp", "keycloak", id="wrong-exact-version"),
    ],
)
def test_product_licence_requires_corroborating_release(tmp_path, file, kind, entity, slot, value, service, product):
    pack = copy_platform(tmp_path)
    path = pack / "facts" / f"{file}.yaml"
    facts = yaml.safe_load(path.read_text(encoding="utf-8"))
    row, = [r for r in facts[kind] if r["id"] == entity]
    if value is None:
        del row[slot]
    else:
        row[slot] = value
    path.write_text(yaml.safe_dump(facts, sort_keys=False), encoding="utf-8")

    result = publication(pack, tmp_path / "published")
    assert ("pin-db-git", "postgresql-16") in snapshot(result, "pin__release")
    for role in ("platform-catalogue", "checker"):
        versions = {row[2] for row in snapshot(result, "component_product_licence", role) if row[:2] == (service, product)}
        assert versions == set()
        states = {row[2] for row in snapshot(result, "component_licence_state", role) if row[:2] == (service, product)}
        assert states == {"unknown-selected-release"}
