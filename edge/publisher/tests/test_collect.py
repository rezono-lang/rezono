"""The collector: it deletes what no retained manifest needs, in an order no reader can trip over, and every
retained manifest still has every object it names, with its hash."""

import json
import os
import time

import pytest

from rezono_publisher import collect, kept, pointers, publish, store
from test_publish import ROLES, epoch

OLD = time.time() - 3 * collect.DAY


def diagnosis(st, did: str, n: int, last_good: str) -> None:
    data = json.dumps({"id": did, "epoch": n, "last_good_manifest": last_good}).encode()
    st.put_new(f"toy/diagnoses/{did}.json", data)
    pointers.write(st, "toy", "diagnoses", data)


@pytest.fixture
def lab(tmp_path):
    """Three main manifests, a variant and a proposal against the oldest, a view beside each main, two diagnoses
    and a stray object; everything written three days ago."""
    st = store.FileStore(tmp_path / "store")
    m = {n: publish.publish(epoch(epoch=n), st, ROLES) for n in (1, 2, 3)}
    publish.publish(epoch(epoch=2, base_manifest="m-1", variant={"sweep": "rate", "index": 0}), st, ROLES, m[1])
    publish.publish(epoch(epoch=2, base_manifest="m-1", proposal="7"), st, ROLES, m[1])
    for n in (1, 2, 3):
        st.put_new(f"toy/m-{n}/guest/views/index.json", b"{}")  # a sidecar: named by no manifest
    diagnosis(st, "v-rate-01-4", 4, "m-3")
    diagnosis(st, "v-rate-01-1", 1, "")
    st.put_new("toy/objects/" + "0" * 64 + ".json", b"[]")  # named by no manifest
    for p in st.root.rglob("*"):
        os.utime(p, (OLD, OLD))
    return st


def manifests(st):
    return sorted(k.split("/")[-1][:-5] for k in st.list("toy/manifests/"))


def complete(st, mid):
    """Every object the manifest names is there with its hash (kept.references), and so are its head or pointer."""
    data = st.get(f"toy/manifests/{mid}.json")
    return kept.references(json.loads(data), st) == [] and all(
        st.get(k) == b for k, b in pointers.pointers("toy", "manifests", data))


def test_only_the_newest_main_is_kept_when_no_proposal_is_open(lab):
    out = collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert out["retained"] == ["m-3"] and manifests(lab) == ["m-3"] and complete(lab, "m-3")
    assert publish.newest_main(lab, "toy")["id"] == "m-3"
    assert lab.list("toy/m-1/") == lab.list("toy/m-2/") == [] and lab.list("toy/m-3/guest/views/")
    assert lab.list("toy/bases/") == lab.list("toy/epochs/2/") == []
    # Content keys: what m-3 shares with the others stays, the stray object goes.
    named = {u[len(lab.uri("")):] for u in publish.named(json.loads(lab.get("toy/manifests/m-3.json")))}
    assert set(lab.list("toy/objects/")) == {k for k in named if k.startswith("toy/objects/")}
    # A diagnosis is kept with its pointer when its last good manifest is kept or it is not older than it.
    assert lab.list("toy/diagnoses/") == ["toy/diagnoses/v-rate-01-4.json"] and lab.list("toy/epochs/4/")
    # Heads and pointers go before the manifests they point to, and those before their objects.
    order = [k.split("/")[1] for k in out["delete"]]
    assert order.index("manifests") > max(i for i, t in enumerate(order) if t in collect.FIRST)
    assert order.index("m-1") > max(i for i, t in enumerate(order) if t in collect.THEN)


def test_an_open_proposal_keeps_its_base_and_the_base_keeps_its_variants(lab):
    out = collect.collect(lab, "toy", keep_main=1)  # without a list every proposal counts as open
    assert out["retained"] == ["m-1", "m-3", "p-7-2", "v-rate-00-2"]
    assert manifests(lab) == out["retained"] and all(complete(lab, m) for m in out["retained"])
    assert lab.list("toy/m-2/") == []


def test_a_kept_manifest_and_the_newest_n_are_retained(lab):
    assert collect.collect(lab, "toy", keep_main=2, keep={"m-1"}, open_proposals=set())["retained"] == [
        "m-1", "m-2", "m-3", "v-rate-00-2"]
    assert all(complete(lab, m) for m in manifests(lab))


def test_nothing_younger_than_the_grace_period_is_deleted(lab):
    """A publication writes its objects before its manifest: what no manifest names yet may be one in flight."""
    st = lab
    st.put_new("toy/objects/" + "1" * 64 + ".json", b"[1]")  # written now
    out = collect.plan(st, "toy", keep_main=1, open_proposals=set())
    assert "toy/objects/" + "1" * 64 + ".json" not in out["delete"] and out["young"] == 1
    assert collect.plan(st, "toy", keep_main=1, open_proposals=set(), now=OLD)["delete"] == []


def test_a_key_in_no_known_namespace_is_left(lab):
    lab.put_new("toy/m-9/guest/views/index.json", b"{}")  # the views of a manifest not written yet
    os.utime(lab.root / "toy/m-9/guest/views/index.json", (OLD, OLD))
    out = collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert out["unknown"] == ["toy/m-9/guest/views/index.json"] and lab.get("toy/m-9/guest/views/index.json")


@pytest.mark.parametrize("bad", [b"not json", b'{"id": "m-8"}', b"[]"])
def test_a_manifest_that_cannot_be_read_stops_the_collector_before_any_delete(lab, bad):
    lab.put_new("toy/manifests/m-7.json", bad)
    before = lab.list("toy/")
    with pytest.raises(ValueError):
        collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert lab.list("toy/") == before


def test_keep_main_is_at_least_one(lab):
    with pytest.raises(ValueError, match="at least 1"):
        collect.plan(lab, "toy", keep_main=0)


def test_the_command_is_a_dry_run_unless_it_is_told_to_delete(lab, tmp_path, capsys, monkeypatch):
    url = "file:///the-store"
    monkeypatch.setattr(collect.stores, "open_store", lambda u, e=None: lab if u == url else None)
    before = lab.list("toy/")
    assert collect.main(["toy", "--store", url, "--keep-main", "3"]) == 0
    printed = capsys.readouterr().out.splitlines()
    assert lab.list("toy/") == before and printed and all(x.startswith("would delete ") for x in printed)
    opened = tmp_path / "open.json"
    opened.write_text("[]", encoding="utf-8")
    assert collect.main(["toy", "--store", url, "--keep-main", "3", "--open-proposals", str(opened), "--delete"]) == 0
    assert manifests(lab) == ["m-1", "m-2", "m-3", "v-rate-00-2"]


def test_no_head_stops_the_collector(lab):
    for k in lab.list("toy/heads/"):
        os.remove(lab.root / k)
    with pytest.raises(ValueError, match="no head"):
        collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert manifests(lab) == ["m-1", "m-2", "m-3", "p-7-2", "v-rate-00-2"]


def test_a_newer_manifest_without_a_head_stops_the_collector(lab):
    """A publication that stopped between its manifest and its head: the gate serves the one before."""
    head = pointers.pointers("toy", "manifests", lab.get("toy/manifests/m-3.json"))[0][0]
    os.remove(lab.root / head)
    before = lab.list("toy/")
    with pytest.raises(ValueError, match="m-3 is newer than the served m-2"):
        collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert lab.list("toy/") == before


def test_no_main_manifest_retained_stops_the_collector(tmp_path):
    st = store.FileStore(tmp_path)
    publish.publish(epoch(epoch=2, base_manifest="m-1", proposal="7"), st, ROLES)
    with pytest.raises(ValueError, match="no main manifest is retained"):
        collect.plan(st, "toy", keep_main=1)


def test_a_publication_beside_the_collector_stops_it_before_the_objects(lab, monkeypatch):
    """A proposal against m-1 (outside the retained set) takes over m-1's objects after the plan read the store."""
    planned = collect.plan

    def plan_then_publish(*a, **kw):
        out = planned(*a, **kw)
        base = json.loads(lab.get("toy/manifests/m-1.json"))
        publish.publish(epoch(epoch=4, base_manifest="m-1", proposal="9"), lab, ROLES, base)
        return out

    monkeypatch.setattr(collect, "plan", plan_then_publish)
    with pytest.raises(ValueError, match="published while the collector ran: p-9-4"):
        collect.collect(lab, "toy", keep_main=1, open_proposals=set())
    assert complete(lab, "p-9-4") and complete(lab, "m-1")


def test_a_retained_manifest_naming_what_the_store_does_not_list_stops_the_collector(lab):
    m = json.loads(lab.get("toy/manifests/m-3.json"))
    os.remove(lab.root / collect.key_of(m["witnesses"][0]["uri"]))
    with pytest.raises(ValueError, match="m-3 names what the store does not list"):
        collect.plan(lab, "toy", keep_main=1, open_proposals=set())


def test_the_command_refuses_an_absent_kept_id_bad_open_proposals_and_a_negative_grace(lab, tmp_path, monkeypatch):
    url = "file:///the-store"
    monkeypatch.setattr(collect.stores, "open_store", lambda u, e=None: lab if u == url else None)
    before = lab.list("toy/")
    assert collect.main(["toy", "--store", url, "--keep-main", "1", "--keep", "m-99", "--delete"]) == 1
    assert collect.main(["toy", "--store", url, "--keep-main", "1", "--grace-seconds", "-1"]) == 1
    opened = tmp_path / "open.json"
    opened.write_text("[7]", encoding="utf-8")
    with pytest.raises(SystemExit):
        collect.main(["toy", "--store", url, "--keep-main", "1", "--open-proposals", str(opened), "--delete"])
    assert lab.list("toy/") == before
