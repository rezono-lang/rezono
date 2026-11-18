"""Inline publication of two disjoint, hand-authored role snapshots of one kind."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from rezono_publisher import forms, publish, store


def staged(st):
    """The upstream snapshot planner has finished. The form pipeline uses the real local store."""
    files = []

    def entry(key, value):
        data = json.dumps(value).encode()
        files.append((key, data))
        return {"uri": st.uri(key), "sha256": hashlib.sha256(data).hexdigest()}

    bundle = {"pack": {"id": "toy"}, "kinds": [{"id": "item", "class": "Item", "world": "closed"}],
              "attributes": [], "arrows": [], "relations": []}
    compiled = entry("toy/inputs/bundle", bundle)
    snaps = []
    for role, ids in [("east", ["amber"]), ("west", ["blue"]), ("all", ["amber", "blue", "grey"])]:
        snapshot = entry(f"toy/inputs/{role}", [{"key": [i]} for i in ids])
        snaps.append({**snapshot, "relation": "item", "role": role, "complete": role == "all"})
    manifest = {"id": "m-1", "epoch": 1, "knowledge_time": "2026-01-01T00:00:00Z",
                "definition_sha256": "a" * 64, "access_semantics": 2, "snapshots": snaps,
                "compiled": [{**compiled, "file": "bundle/schema-bundle.json"}]}
    return files, manifest


def publish_inline(st, monkeypatch):
    monkeypatch.setattr(publish, "plan", lambda *args: staged(st))
    return publish.publish(SimpleNamespace(pack="toy"), st, {}, forms=True)


def test_role_forms_have_scoped_bytes_and_repeat_exactly(tmp_path, monkeypatch):
    builds = []
    for number in range(2):
        st = store.FileStore(tmp_path / str(number))
        publish_inline(st, monkeypatch)
        made = {key: st.get(key) for key in st.list("toy/m-1/")}
        expected_keys = set()
        for role, item in [("east", "amber"), ("west", "blue")]:
            prefix = f"toy/m-1/{role}/publication/"
            index_key = prefix + "index.json"
            index = json.loads(made[index_key])
            assert index["role"] == role
            expected_keys.add(index_key)
            assert {"rows.json", "schema.json", "hashes.json", "statement.json"} <= {
                obj["name"] for obj in index["objects"]}
            for obj in index["objects"]:
                key = prefix + obj["name"]
                assert obj["uri"] == st.uri(key)
                assert hashlib.sha256(made[key]).hexdigest() == obj["sha256"]
                expected_keys.add(key)
            rows = json.loads(made[prefix + "rows.json"])
            assert rows["$rows"] == [{"$kind": "Item", "$id": item}]
        assert set(made) == expected_keys
        builds.append(made)
    assert builds[0] == builds[1]


def test_bad_second_role_holds_back_every_form_and_the_manifest(tmp_path, monkeypatch):
    st = store.FileStore(tmp_path)
    encode = forms.objects

    def corrupt(form):
        data = encode(form)
        if form["role"] == "west":
            rows = json.loads(data["rows.json"])
            rows["$rows"][0]["$id"] = "substituted"
            data["rows.json"] = json.dumps(rows).encode()
        return data

    monkeypatch.setattr(forms, "objects", corrupt)
    with pytest.raises(forms.Blocked, match="role west: publication form: the bytes do not read back"):
        publish_inline(st, monkeypatch)
    assert st.list("toy/m-1/") == []
    assert st.list("toy/manifests/") == []
    assert st.list("toy/heads/") == []
