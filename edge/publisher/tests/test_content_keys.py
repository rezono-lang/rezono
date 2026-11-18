"""Content-addressed objects: a role's snapshots, witness set, asset index and source set are keyed by
the hash of their bytes, so an unchanged pack writes a manifest and its head only, a changed fact writes only the
objects that changed, two roles with the same bytes share one object, and the collector then deletes what no retained
manifest names while every retained manifest stays complete."""

import dataclasses
import json
import os
import time

from rezono_publisher import collect, kept, pointers, publish, store
from test_publish import ROLES, SALARIES, epoch


class Counting(store.FileStore):
    """A file store that records every key a put made new."""

    def __init__(self, root):
        super().__init__(root)
        self.new: list[str] = []

    def put_new(self, key, data):
        fresh = self.get(key) is None
        super().put_new(key, data)
        if fresh:
            self.new.append(key)


def key(st, uri: str) -> str:
    assert uri.startswith(st.uri(""))
    return uri[len(st.uri("")):]


def entries(m: dict) -> list[dict]:
    return [x for s in ("snapshots", "witnesses", "assets", "fact_sources") for x in m.get(s, [])]


def test_the_same_pack_published_again_writes_a_manifest_and_its_head_only(tmp_path):
    st = Counting(tmp_path)
    m1 = publish.publish(epoch(epoch=1), st, ROLES)
    assert all(key(st, x["uri"]) == publish.object_key("toy", st.get(key(st, x["uri"]))) for x in entries(m1))
    st.new.clear()
    m2 = publish.publish(epoch(epoch=2), st, ROLES, reuse=m1)
    assert st.new == ["toy/manifests/m-2.json", pointers.pointers("toy", "manifests", st.get("toy/manifests/m-2.json"))[0][0]]
    assert [x["uri"] for x in entries(m2)] == [x["uri"] for x in entries(m1)]


def test_one_changed_fact_writes_only_the_objects_that_changed(tmp_path):
    st = Counting(tmp_path)
    m1 = publish.publish(epoch(epoch=1), st, ROLES)
    changed = epoch(epoch=2, salaries=SALARIES + [("b", "7")])
    files, m2 = publish.plan(changed, st, ROLES, reuse=m1)
    before = {(x.get("relation"), x["role"]): x["sha256"] for x in m1["snapshots"]}
    moved = {(x.get("relation"), x["role"]) for x in m2["snapshots"] if before.get((x.get("relation"), x["role"])) != x["sha256"]}
    assert moved and {rel for rel, _ in moved} <= {"salary", "wage", "total"}, moved
    named = publish.named(m1)
    assert sorted(k for k, _ in files) == sorted({key(st, x["uri"]) for x in entries(m2) if x["uri"] not in named})
    assert len(files) < len(entries(m2)) / 2, "most objects are the first manifest's"
    # The manifest's bytes do not depend on what was published before: content keys, not reuse, name the objects.
    _, alone = publish.plan(changed, store.FileStore(tmp_path / "empty"), ROLES)
    assert alone == m2


def test_two_roles_with_the_same_bytes_share_one_object(tmp_path):
    st = Counting(tmp_path)
    files, m = publish.plan(epoch(full=True), st, ROLES)  # every role reads every node in full: the same bytes
    uri = {(x.get("relation"), x["role"]): x["uri"] for x in m["snapshots"] + m["witnesses"]}
    assert uri[("node", "guest")] == uri[("node", "checker")]
    assert uri[(None, "guest")] == uri[(None, "checker")]  # the witness sets
    assert len({k for k, _ in files}) == len(files), "each object once"
    assert len(files) < len(m["snapshots"]) + len(m["witnesses"])


def test_the_collector_deletes_what_only_an_older_manifest_named(tmp_path):
    st = store.FileStore(tmp_path)
    m1 = publish.publish(epoch(epoch=1), st, ROLES)
    m2 = publish.publish(epoch(epoch=2, salaries=SALARIES + [("b", "7")]), st, ROLES, reuse=m1)
    old = time.time() - 3 * collect.DAY
    for p in st.root.rglob("*"):
        os.utime(p, (old, old))
    gone = {key(st, x["uri"]) for x in entries(m1)} - {key(st, x["uri"]) for x in entries(m2)}
    assert gone
    out = collect.collect(st, "toy", keep_main=1, open_proposals=set())
    assert out["retained"] == ["m-2"] and gone <= set(out["delete"])
    assert kept.references(json.loads(st.get("toy/manifests/m-2.json")), st) == []
    assert all(st.get(k) is None for k in gone)
    assert sorted(st.list("toy/objects/")) == sorted({key(st, x["uri"]) for x in entries(m2)})


def test_a_variant_writes_only_what_its_base_lacks(tmp_path):
    st = Counting(tmp_path)
    base = publish.publish(epoch(epoch=1), st, ROLES)
    variant = dataclasses.replace(epoch(epoch=2, salaries=SALARIES + [("b", "7")]), base_manifest="m-1",
                                  variant={"sweep": "rate", "index": 0})
    files, m = publish.plan(variant, st, ROLES, base)
    assert files and all(st.uri(k) not in publish.named(base) for k, _ in files)
    assert {x["uri"] for x in entries(m)} & publish.named(base), "what did not change is the base's object"


def test_role_objects_follow_the_manifest(tmp_path):
    st = store.FileStore(tmp_path)
    m = publish.publish(epoch(), st, ROLES)
    mine = publish.role_objects(st, "toy", "m-1", "guest")
    assert set(mine) == {f"relations/{x['relation']}.json" for x in m["snapshots"] if x["role"] == "guest"} | {"witnesses.json"}
    assert all(k.startswith("toy/objects/") and st.get(k) is not None for k in mine.values())
    assert publish.role_objects(st, "toy", "m-9", "guest") == {}
