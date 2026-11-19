"""The standard pack std-access written in Rezono has the meaning of its existing schema and rule files.

The pack publishes nothing on its own: a consumer gives it roles and read grants. examples/subsidy is that
consumer here. It is published twice: once over std-access with its existing schema and rule files, kept as
the oracle in fixtures/std-access-legacy, and once over std-access as the repository holds it. The two
publications must agree on files, bundle (places aside) and the relations each role sees
(decisions/language-semantic-publication.md, decisions/language-first-packs.md)."""

from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, modules, pack
from rezono_publisher import batch, publish, store


REPO = Path(__file__).resolve().parents[3]
ORACLE = Path(__file__).resolve().parent / "fixtures/std-access-legacy"
ACCESS = "packs/std-access"
CONSUMER = "examples/subsidy"
LEGACY = ("schema/access.yaml", "rules/access.dl")
MODULE = "rezono/access.rezono"
ROLES = {"checker": "complete", "case_officer": "may_read", "policy_adviser": "may_read", "public": "may_read"}


def published(tmp_path, form):
    root = tmp_path / form
    shutil.copytree(REPO / "packs", root / "packs")
    for example in (CONSUMER, "examples/subsidy-scheme"):
        shutil.copytree(REPO / example, root / example)
    access = root / ACCESS
    meta_path = access / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    if form == "legacy":
        shutil.rmtree(access / "rezono", ignore_errors=True)
        for name in LEGACY:
            (access / name).parent.mkdir(exist_ok=True)
            shutil.copy(ORACLE / name, access / name)
        meta.pop("rezono", None)
        meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    else:
        assert not any((access / name).exists() for name in LEGACY), "the module replaces the schema and rules"
        assert [entry["module"] for entry in meta.get("rezono") or []] == [MODULE]
    consumer = root / CONSUMER
    consumer_meta = yaml.safe_load((consumer / "pack.yaml").read_bytes())
    for entry in consumer_meta["imports"]:
        if entry["name"] == "std-access":
            entry["sha256"] = modules.pack_hash(access)
    (consumer / "pack.yaml").write_text(yaml.safe_dump(consumer_meta, sort_keys=False), encoding="utf-8")
    files = emit.compile_pack(pack.read(consumer))
    epoch = batch.epoch(consumer, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
    bucket = store.FileStore(tmp_path / f"{form}-store")
    publish.publish(epoch, bucket, ROLES)
    seen = {}
    for role in ROLES:
        objects = publish.role_objects(bucket, "subsidy", "m-1", role)
        assert objects, role
        seen[role] = {name[len("relations/"):-len(".json")]: sorted(repr(row["key"]) for row in
                                                                     json.loads(bucket.get(key)))
                      for name, key in objects.items() if name.startswith("relations/")}
    return files, seen


def unplaced(value):
    """The bundle with each place in std-access reduced to one name: its file and lines may differ."""
    sources = {MODULE, *LEGACY} | {f"std-access/{name}" for name in (MODULE, *LEGACY)}
    if isinstance(value, dict):
        if value.get("file") in sources:
            return {"file": "std-access"}
        return {k: unplaced(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unplaced(v) for v in value]
    return value


def meaning(result):
    files, seen = result
    return {
        "files": sorted(files),
        "bundle": unplaced(json.loads(files["bundle/schema-bundle.json"])),
        "seen": seen,
    }


def test_the_oracle_is_the_existing_std_access():
    for name in LEGACY:
        if (REPO / ACCESS / name).exists():
            assert (REPO / ACCESS / name).read_bytes() == (ORACLE / name).read_bytes(), name


def test_std_access_publishes_through_its_consumer(tmp_path):
    _, seen = published(tmp_path, "legacy")
    # The public reads the scheme and never a case; the case officer reads the cases (examples/subsidy,
    # rules/access.dl). Without these the comparison below could agree on two empty worlds.
    assert seen["public"]["article"] and seen["public"]["article"] == seen["case_officer"]["article"]
    assert not seen["public"].get("application")
    assert seen["case_officer"]["application"]


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "M3: decisions/language-first-packs.md: Replace schema/access.yaml and rules/access.dl of packs/std-access "
    "with rezono/access.rezono and rezono/access.json, declared in its pack.yaml, starting from what "
    "scripts/convert_pack.py proposes, so that examples/subsidy publishes the same files, bundle (places "
    "aside) and relations per role over it as over the oracle in "
    "compiler/tests/rezono/fixtures/std-access-legacy. Update the sha256 of std-access in every pack.yaml "
    "that imports it, and onwards for their importers; this task may change those lines. Waits for "
    "test_lower_schema_annotations, which lowers the schema metadata of the pack."))
def test_whole_std_access_has_the_same_meaning(tmp_path):
    expected = meaning(published(tmp_path, "legacy"))
    actual = meaning(published(tmp_path, "rezono"))
    assert actual == expected
