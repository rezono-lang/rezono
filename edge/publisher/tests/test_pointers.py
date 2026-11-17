"""Heads of main manifests (rezono_publisher.pointers): the newest sorts first, the backfill is idempotent."""

import hashlib
import json

import pytest

from rezono_publisher import pointers, store


def manifest(st, pack, body):
    data = json.dumps(body, sort_keys=True).encode()
    st.put_new(f"{pack}/manifests/{body['id']}.json", data)
    return data


def test_heads_sort_newest_first_and_the_backfill_writes_each_once(tmp_path):
    st = store.FileStore(tmp_path)
    nine = manifest(st, "p", {"id": "m-9", "epoch": 9})
    manifest(st, "p", {"id": "m-10", "epoch": 10})
    manifest(st, "p", {"id": "p-x-11", "epoch": 11, "proposal": "x", "base_manifest": "m-10"})
    manifest(st, "p", {"id": "v-price-00-11", "epoch": 11, "variant": {"sweep": "price", "index": 0, "value": "0"}})
    st.put_new("p/diagnoses/v-price-01-11.json", json.dumps({"id": "v-price-01-11", "epoch": 11}).encode())
    written = pointers.backfill(st, "p")
    assert written == sorted([pointers.head_key("p", 9), pointers.head_key("p", 10), "p/bases/m-10/p-x-11.json",
                              "p/epochs/11/manifests/v-price-00-11.json", "p/epochs/11/diagnoses/v-price-01-11.json"])
    ref = json.loads(st.get("p/bases/m-10/p-x-11.json"))
    assert ref == {"format": "rezono.pointer/1", "id": "p-x-11", "sha256": hashlib.sha256(st.get("p/manifests/p-x-11.json")).hexdigest()}
    first = sorted(st.list("p/heads/"))[0]
    assert json.loads(st.get(first))["manifest"] == "m-10", "the newest epoch sorts first, not m-10 < m-9 as text"
    h = json.loads(st.get(pointers.head_key("p", 9)))
    assert h == {"format": "rezono.head/1", "manifest": "m-9", "epoch": 9, "sha256": hashlib.sha256(nine).hexdigest()}
    assert pointers.backfill(st, "p") == [], "idempotent"
    assert pointers.head("p", nine) == (pointers.head_key("p", 9), st.get(pointers.head_key("p", 9))), "the publisher's bytes"


def test_a_head_with_other_bytes_is_a_conflict(tmp_path):
    st = store.FileStore(tmp_path)
    manifest(st, "p", {"id": "m-1", "epoch": 1})
    st.put_new(pointers.head_key("p", 1), b"{}")
    with pytest.raises(store.Conflict):
        pointers.backfill(st, "p")


class Stops(store.FileStore):
    """A store whose writes stop after the first: a backfill stopped halfway."""

    def put_new(self, key, data):
        if getattr(self, "stopped", False):
            raise OSError("stopped")
        super().put_new(key, data)
        if "/heads/" in key:
            self.stopped = True


def test_a_backfill_stopped_halfway_leaves_the_newest_head_first(tmp_path):
    st = Stops(tmp_path)
    for n in (1, 9, 10):
        manifest(st, "p", {"id": f"m-{n}", "epoch": n})
    with pytest.raises(OSError):
        pointers.backfill(st, "p")
    assert st.list("p/heads/") == [pointers.head_key("p", 10)], "the newest, never an older one alone"
