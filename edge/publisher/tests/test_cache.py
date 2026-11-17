"""A sweep reuses immutable bytes, never a head or a conditional write, and a missing object only under its base."""

import json
from collections import Counter
from threading import Lock

import pytest

from rezono_publisher import store
from rezono_publisher.cache import SweepStore


class CountingStore:
    def __init__(self):
        self.objects, self.reads, self.writes = {}, Counter(), Counter()
        self._lock = Lock()

    def uri(self, key):
        return f"s3://test/{key}"

    def get(self, key):
        self.reads[key] += 1
        return self.objects.get(key)

    def list(self, prefix):
        return sorted(k for k in self.objects if k.startswith(prefix))

    def put_new(self, key, data):
        with self._lock:
            self.writes[key] += 1
            if key in self.objects and self.objects[key] != data:
                raise store.Conflict(key)
            self.objects[key] = data


def test_base_reads_are_reused_and_fresh_variant_bytes_need_no_round_trip():
    st = CountingStore()
    base = "p/m-1/viewer/relations/a.json"
    st.put_new(base, b"base")
    cache = SweepStore(st, "p", "m-1")
    for i in range(4):
        vid = f"v-x-0{i}-2"
        cache.begin(vid)
        for _ in range(3):
            assert cache.get(base) == b"base"
        own = f"p/{vid}/viewer/relations/a.json"
        cache.put_new(own, b"changed")
        assert cache.get(own) == b"changed"
        assert st.reads[own] == 0
    assert st.reads[base] == 1
    assert cache.counts() == {"get": 1, "hit": 15, "put": 4, "get_bytes": 4, "put_bytes": 28}


def test_heads_lists_missing_objects_and_other_namespaces_stay_fresh():
    st, base = CountingStore(), "p/manifests/m-1.json"
    cache = SweepStore(st, "p", "m-1")
    cache.begin("v-x-00-2")
    assert cache.get(base) is None
    st.put_new(base, b"published")
    assert cache.get(base) == b"published"  # no negative cache
    for key in ("p/heads/1.json", "p/epochs/2/x.json", "q/m-1/viewer/x.json"):
        st.objects[key] = b"before"
        assert cache.get(key) == b"before"
        st.objects[key] = b"after"
        assert cache.get(key) == b"after"
        assert st.reads[key] == 2
    assert cache.list("p/manifests/") == [base]
    st.put_new("p/manifests/m-2.json", b"new")
    assert cache.list("p/manifests/") == [base, "p/manifests/m-2.json"]


def test_what_the_base_lacks_is_asked_once_a_sweep_and_no_other_miss_is_remembered():
    """RV-M24: every variant asks for its role's view index of the base (rezono_publisher.difference.shared). The
    base is published before its sweep and the sweep writes nothing under it, so a miss there stands for the
    whole sweep. A miss anywhere else may be an object that is about to be written."""
    st = CountingStore()
    cache = SweepStore(st, "p", "m-1")
    lacking = "p/m-1/viewer/views/index.json"
    for i in range(3):
        cache.begin(f"v-x-0{i}-2")
        assert cache.get(lacking) is None and cache.get(lacking) is None
    assert st.reads[lacking] == 1
    for key in ("p/v-x-02-2/viewer/explain/index.json", "p/manifests/v-x-02-2.json",  # the variant's own
                "p/m-10/viewer/views/index.json", "q/m-1/viewer/views/index.json"):  # another base, another pack
        assert cache.get(key) is None and cache.get(key) is None
        assert st.reads[key] == 2
    cache.put_new(lacking, b"{}")  # a write through the cache is never hidden by a remembered miss
    assert cache.get(lacking) == b"{}" and st.reads[lacking] == 1


def test_cache_does_not_skip_conditional_writes_or_hide_a_conflict():
    st = CountingStore()
    cache = SweepStore(st, "p", "m-1")
    key = "p/m-1/viewer/relations/a.json"
    cache.put_new(key, b"same")
    assert cache.get(key) == b"same"
    cache.put_new(key, b"same")
    with pytest.raises(store.Conflict):
        cache.put_new(key, b"different")
    assert st.writes[key] == 3 and cache.get(key) == b"same"


def test_only_the_base_survives_the_next_variant_and_roles_have_separate_keys():
    st = CountingStore()
    cache = SweepStore(st, "p", "m-1")
    cache.begin("v-x-00-2")
    base, first = "p/manifests/m-1.json", "p/manifests/v-x-00-2.json"
    for key in (base, first):
        cache.put_new(key, b"manifest")
    for role in ("viewer", "private"):
        cache.put_new(f"p/v-x-00-2/{role}/relations/a.json", role.encode())
    assert cache.get("p/v-x-00-2/viewer/relations/a.json") == b"viewer"
    assert cache.get("p/v-x-00-2/private/relations/a.json") == b"private"
    cache.begin("v-x-01-2")
    assert cache.get(base) == b"manifest" and st.reads[base] == 0
    assert cache.get(first) == b"manifest" and st.reads[first] == 1
    assert cache.get(first) == b"manifest" and st.reads[first] == 2


def test_concurrent_publication_writes_still_reach_the_store():
    st = CountingStore()
    cache = SweepStore(st, "p", "m-1")
    files = [(f"p/m-1/viewer/relations/r{i}.json", str(i).encode()) for i in range(32)]
    store.put_all(cache, files)
    assert cache.counts()["put"] == len(files)
    assert all(cache.get(k) == data and st.writes[k] == 1 for k, data in files)
    assert not st.reads


def test_snapshots_are_read_side_by_side_in_the_order_asked():
    """RV-M24: the first variant of the lab's sweep read 658 snapshots one after another, 70 s of round trips.
    A read waits on the store, so several are in flight at once; what comes back is in the order asked."""
    from threading import Barrier

    from rezono_publisher import views

    together = Barrier(2, timeout=30)  # passes only when two reads are in flight at the same time

    class Slow(CountingStore):
        def get(self, key):
            together.wait()
            return super().get(key)

    st = Slow()
    snaps = []
    for i in range(8):
        key, data = f"p/m-1/viewer/relations/r{i}.json", f"[{i}]".encode()
        st.put_new(key, data)
        snaps.append({"relation": f"r{i}", "uri": st.uri(key), "sha256": views.sha256(data)})
    assert views._snapshots(st, snaps) == {f"r{i}": f"[{i}]".encode() for i in range(8)}
    assert all(st.reads[views.key_of(s["uri"])] == 1 for s in snaps)
    cache = SweepStore(CountingStore(), "p", "m-1")
    for s in snaps:
        cache.st.put_new(views.key_of(s["uri"]), st.objects[views.key_of(s["uri"])])
    first, again = views._snapshots(cache, snaps), views._snapshots(cache, snaps)
    assert first == again and cache.counts()["get"] == 8 and cache.counts()["hit"] == 8


def test_a_snapshot_read_side_by_side_is_still_the_object_its_manifest_names():
    from rezono_publisher import views

    st = CountingStore()
    st.put_new("p/m-1/viewer/relations/a.json", b"[]")
    st.put_new("p/m-1/viewer/relations/b.json", b"[1]")
    named = lambda rel, data: {"relation": rel, "uri": st.uri(f"p/m-1/viewer/relations/{rel}.json"),
                               "sha256": views.sha256(data)}
    with pytest.raises(ValueError, match="b.json does not have the sha256 that names it"):
        views._snapshots(st, [named("a", b"[]"), named("b", b"[2]")])
    with pytest.raises(ValueError, match="c.json is not in the store"):
        views._snapshots(st, [named("a", b"[]"), named("c", b"[]")])
    assert store.get_all(st, []) == [] and store.get_all(st, ["p/none"]) == [None]


def test_the_base_objects_survive_the_next_variant_and_a_variant_objects_do_not():
    """RV-Z01: objects are keyed by their bytes, not by manifest: the base manifest says which are the base's."""
    st = CountingStore()
    cache = SweepStore(st, "p", "m-1")
    cache.begin("v-x-00-2")
    mine, theirs = "p/objects/" + "a" * 64 + ".json", "p/objects/" + "b" * 64 + ".json"
    manifest = {"id": "m-1", "snapshots": [{"relation": "a", "role": "viewer", "uri": f"s3://rezono/{mine}"}]}
    cache.put_new("p/manifests/m-1.json", json.dumps(manifest).encode())
    cache.put_new(mine, b"[]")
    cache.put_new(theirs, b"[1]")
    cache.begin("v-x-01-2")
    assert cache.get(mine) == b"[]" and st.reads[mine] == 0
    assert cache.get(theirs) == b"[1]" and st.reads[theirs] == 1
