"""The standard pack std-access written in Rezono has the meaning of its existing schema and rule files.

The pack publishes nothing on its own: a consumer gives it roles and read grants. examples/subsidy is that
consumer here. It is published twice: once over std-access with its existing schema and rule files, kept as
the oracle in fixtures/std-access-legacy, and once over std-access as the repository holds it. The two
publications must agree on files, bundle (places and the pin of std-access aside) and the relations each role
sees (decisions/language-semantic-publication.md, decisions/language-first-packs.md). Each publication's pin of
std-access is checked against its own bytes before it is set aside.

The legacy form is not the standard pack: its bytes differ, so the name std-access is reserved against them
(decisions/standard-pack-names.md). It is published inside a conversion trial, the one place where candidate
bytes are compared under a standard name, and the test checks that they are refused outside it. The form the
repository holds needs no trial: it is the standard pack."""

from contextlib import nullcontext
from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, modules, pack, standard_packs
from rezono_publisher import batch, publish, store
from calc_packs import SCHEME


REPO = Path(__file__).resolve().parents[3]
ORACLE = Path(__file__).resolve().parent / "fixtures/std-access-legacy"
ACCESS = "packs/std-access"
CONSUMER = "examples/subsidy"
LEGACY = ("schema/access.yaml", "rules/access.dl")
MODULE = "rezono/access.rezono"


def published(tmp_path, form):
    root = tmp_path / form
    shutil.copytree(REPO / "packs", root / "packs")
    for example in (CONSUMER, SCHEME):
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
    pin = modules.pack_hash(access)
    if form == "legacy":
        assert standard_packs.refusal("std-access", pin), "the legacy form must not pass as the standard pack"
        admitted = standard_packs.trial("std-access", pin)
    else:
        admitted = nullcontext()
    with admitted:
        files = emit.compile_pack(pack.read(consumer))
        epoch = batch.epoch(consumer, epoch=1, knowledge_time="2026-11-10T00:00:00Z", sources=[("rules", "test")])
        bucket = store.FileStore(tmp_path / f"{form}-store")
        roles = {"checker": "complete"} | {str(row["id"]): "may_read" for row in
                                           yaml.safe_load((consumer / "facts/roles.yaml").read_bytes())["role"]}
        publish.publish(epoch, bucket, roles)
    seen = {}
    for role in roles:
        objects = publish.role_objects(bucket, "subsidy", "m-1", role)
        assert objects, role
        seen[role] = {name[len("relations/"):-len(".json")]: sorted(repr(row["key"]) for row in
                                                                     json.loads(bucket.get(key)))
                      for name, key in objects.items() if name.startswith("relations/")}
    return files, seen, pin


def unplaced(value):
    """The bundle with each place in std-access reduced to one name: its file and lines may differ. An imported
    place is named `std-access:<file>` (compiler/rezono_compiler/spans.py, `where`)."""
    sources = {MODULE, *LEGACY} | {f"std-access{sep}{name}" for name in (MODULE, *LEGACY) for sep in "/:"}
    if isinstance(value, dict):
        if value.get("file") in sources:
            return {"file": "std-access"}
        return {k: unplaced(v) for k, v in value.items()}
    if isinstance(value, list):
        return [unplaced(v) for v in value]
    return value


def unpinned(bundle, pin):
    """The bundle with the pin of std-access set aside, after checking it against this publication's own bytes:
    each form pins its own files, so the hashes differ while the meaning agrees."""
    imports = [entry for entry in bundle.get("imports", []) if entry["name"] == "std-access"]
    assert [entry["sha256"] for entry in imports] == [pin], imports
    for entry in imports:
        entry["sha256"] = "own bytes"
    return bundle


def meaning(result):
    files, seen, pin = result
    return {
        "files": sorted(files),
        "bundle": unplaced(unpinned(json.loads(files["bundle/schema-bundle.json"]), pin)),
        "seen": seen,
    }


def test_the_oracle_is_the_existing_std_access():
    for name in LEGACY:
        if (REPO / ACCESS / name).exists():
            assert (REPO / ACCESS / name).read_bytes() == (ORACLE / name).read_bytes(), name


def test_std_access_publishes_through_its_consumer(tmp_path):
    _, seen, _ = published(tmp_path, "legacy")
    # Every role reads the articles of the scheme; some roles read the applications and some read none
    # (examples/subsidy, rules/access.dl). Without these the comparison below could agree on empty worlds.
    readers = {role: relations for role, relations in seen.items() if role != "checker"}
    articles = {tuple(relations.get("article", [])) for relations in readers.values()}
    assert len(articles) == 1 and all(articles)
    assert any(relations.get("application") for relations in readers.values())
    assert any(not relations.get("application") for relations in readers.values())


def test_whole_std_access_has_the_same_meaning(tmp_path):
    expected = meaning(published(tmp_path, "legacy"))
    actual = meaning(published(tmp_path, "rezono"))
    assert actual == expected
