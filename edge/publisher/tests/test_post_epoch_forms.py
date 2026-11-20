"""Post-epoch forms through the two command-line entry points, with an in-process batch fixture."""

import json
from pathlib import Path

import pytest

from rezono_publisher import __main__ as publisher
from rezono_publisher import batch, forms, publish, store
from test_publish import TOY_ARROWS, TOY_ATTRIBUTES, epoch


BUILD = {"compiler": "synthetic-build-a"}
ROLES = {"all": "complete", "east": "may_read", "west": "may_read"}


@pytest.fixture
def local(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path("toy").mkdir()
    Path("toy/pack.yaml").write_text("name: toy\n")
    configure(True)
    monkeypatch.setattr(batch, "build_record", lambda: dict(BUILD))

    def hand_epoch(pack, **args):
        bundle = {"format": "rezono.schema-bundle/1", "pack": {"id": "toy"},
                  "kinds": [{"id": "node", "class": "Node", "world": "closed"},
                            {"id": "role", "class": "Role", "world": "closed"}],
                  "attributes": TOY_ATTRIBUTES, "arrows": TOY_ARROWS, "relations": [], "checks": []}
        return epoch(epoch=args["epoch"], knowledge_time=args["knowledge_time"], build=dict(BUILD),
                     nodes=["amber", "blue"], edges=[], salaries=[], grants=[("east", "amber"), ("west", "blue")],
                     roles=("east", "west"), bundle=json.dumps(bundle))

    monkeypatch.setattr(batch, "epoch", hand_epoch)
    return store.FileStore("bucket")


def configure(enabled):
    Path("profile.json").write_text(json.dumps({
        "storage": {"url": "file:bucket"}, "access": {"roles": ROLES},
        "publish": {"packs": ["toy"], "classes": ["unclassified"]},
        "forms": {"budget_minutes": 1, "packs": {"toy": enabled}},
    }))


def after(number):
    assert publisher.main(["toy", "--forms-after", "--epoch", str(number), "--knowledge-time",
                           "2026-01-01T00:00:00Z", "--profile", "profile.json"]) == 0


def newest(status, outcome, manifest=None):
    assert forms.main(["--newest", "--profile", "profile.json", "--results", "result.json"]) == status
    expected = {"outcome": outcome}
    if manifest:
        expected["manifest"] = manifest
    assert json.loads(Path("result.json").read_bytes()) == {"toy": expected}


def check_role(st, number, role, node):
    prefix = f"toy/m-{number}/{role}/publication/"
    index = json.loads(st.get(prefix + "index.json"))
    assert (index["manifest"]["id"], index["role"]) == (f"m-{number}", role)
    rows = json.loads(st.get(prefix + "rows.json"))["$rows"]
    assert [(row["$kind"], row["$id"]) for row in rows] == [("Node", node)]


def test_only_the_recorded_build_materialises_the_latest_epoch(local, monkeypatch):
    after(1)
    after(2)
    head = publish.newest_main(local, "toy")
    record = forms.build_of(local, head)
    assert head["id"] == "m-2"
    assert record["compiler"] == BUILD["compiler"]
    assert record["forms"]["format"] == "rezono.publication-form/1"
    assert local.list("toy/m-2/") == []
    with monkeypatch.context() as changed:
        changed.setattr(batch, "build_record", lambda: {"compiler": "synthetic-build-b"})
        newest(0, "foreign", "m-2")
        assert local.list("toy/m-2/") == []
    newest(0, "made", "m-2")
    check_role(local, 2, "east", "amber")
    check_role(local, 2, "west", "blue")
    assert local.list("toy/m-1/") == []


def test_failing_role_leaves_published_manifest_and_other_role_available(local, monkeypatch):
    after(1)
    manifest = local.get("toy/manifests/m-1.json")
    encode = forms.objects

    def corrupt(form):
        data = encode(form)
        if form["role"] == "east":
            rows = json.loads(data["rows.json"])
            rows["$rows"][0]["$id"] = "substituted"
            data["rows.json"] = json.dumps(rows).encode()
        return data

    monkeypatch.setattr(forms, "objects", corrupt)
    newest(2, "red", "m-1")
    assert local.list("toy/m-1/east/publication/") == []
    check_role(local, 1, "west", "blue")
    assert local.get("toy/manifests/m-1.json") == manifest
    assert publish.newest_main(local, "toy")["id"] == "m-1"


def test_new_head_between_roles_stops_work_on_superseded_epoch(local, monkeypatch):
    after(1)
    put = store.FileStore.put_new

    def publish_next(st, key, data):
        put(st, key, data)
        if key == "toy/m-1/east/publication/index.json":
            after(2)

    monkeypatch.setattr(store.FileStore, "put_new", publish_next)
    newest(0, "overtaken", "m-2")
    check_role(local, 1, "east", "amber")
    assert local.list("toy/m-1/west/publication/") == []
    assert publish.newest_main(local, "toy")["id"] == "m-2"
    assert local.list("toy/m-2/") == []


def test_opt_out_omits_the_library_and_skips_the_pack(local):
    configure(False)
    after(1)
    head = publish.newest_main(local, "toy")
    assert head["id"] == "m-1"
    assert "forms" not in forms.build_of(local, head)
    newest(0, "off")
    configure(True)
    newest(1, "refused", "m-1")
    assert local.list("toy/m-1/") == []
