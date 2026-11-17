"""The published views of a manifest (rezono_publisher.views), over every example pack.

Generic: no pack is named. Per filtered role: a view index that names the manifest and exactly the role's
snapshots, pieces that the checker accepts, the same bytes when made again, and positions that stay from
one manifest to the next (the next starts from the previous layout). A view that shows more than its role
reads writes nothing. Needs Node and `npm ci` in viewer/, the compiler and DuckDB.
"""

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store, views  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PACKS = sorted(p.parent for p in (ROOT / "examples").rglob("pack.yaml")
               if "expected" not in p.parts and (p.parent / "facts").is_dir())
ROLES = {"checker": "complete", "viewer": "may_read"}
pytestmark = pytest.mark.skipif(not shutil.which("node") or not (ROOT / "viewer" / "node_modules").is_dir(),
                                reason="needs node and npm ci in viewer/")


def published(pack_dir, st, n):
    e = batch.epoch(pack_dir, epoch=n, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    try:
        return e.pack, publish.publish(e, st, ROLES)["id"]
    except publish.Blocked:
        pytest.skip("a red pack publishes nothing, so it has no views")


@pytest.mark.parametrize("pack_dir", PACKS, ids=lambda p: p.relative_to(ROOT / "examples").as_posix())
def test_views_of_two_manifests(pack_dir, tmp_path):
    st = store.FileStore(tmp_path / "store")
    pack, first = published(pack_dir, st, 1)
    keys = views.publish(st, pack, first)
    assert keys == [views.index_key(pack, first, "viewer")], "a complete role gets no view: the gate serves it nothing"
    m = json.loads(st.get(f"{pack}/manifests/{first}.json"))
    index = json.loads(st.get(keys[0]))
    mine = sorted((s for s in m["snapshots"] if s["role"] == "viewer"), key=lambda s: s["relation"])
    assert index["sources"] == [{"relation": s["relation"], "sha256": s["sha256"]} for s in mine]
    assert (index["manifest"], index["role"], index["relayout"], "previous" in index) == (first, "viewer", False, False)
    # The role's source entries by row (S25), for the set the manifest names; none before S25.
    sets = [x["sha256"] for x in m.get("fact_sources", []) if x["role"] == "viewer"]
    assert [index["fact_sources"]["set"]] == sets if sets else "fact_sources" not in index
    # The overview by meaning: island levels from level 0, and a Map per island, each named by sha256. Level 0
    # is the Map itself (`map`) when it would hold one island that opens a Map. A role that reads no element
    # (the pack's rules grant it none) gets an empty level 0 and no Map.
    bundle = next(c for c in m["compiled"] if c["file"] == "bundle/schema-bundle.json")
    compiled = json.loads(st.get(views.key_of(bundle["uri"])))
    kinds = {k["id"] for k in compiled["kinds"]}
    reads = any(json.loads(st.get(views.key_of(s["uri"]))) for s in mine if s["relation"] in kinds)
    assert ("root" in index["islands"]) != ("map" in index["sheets"])
    # Every Flow and Matrix the pack binds is a sheet like a Map (`flow.<id>`, `matrix.<id>`), whatever the role reads.
    channels = compiled.get("channels", {})
    bound = {f"flow.{f['id']}" for f in channels.get("flows", [])} | {f"matrix.{m['id']}" for m in channels.get("matrices", [])}
    assert bound <= set(index["sheets"])
    assert bool(set(index["sheets"]) - bound) == reads
    named = [*index["islands"].values(), *(s[k] for s in index["sheets"].values() for k in ("root", "layout"))]
    for n in named:
        assert views.sha256(st.get(views.key_of(n["uri"]))) == n["sha256"]
    if "root" in index["islands"]:
        root = json.loads(st.get(views.key_of(index["islands"]["root"]["uri"])))
        assert root["format"] == "rede.islands/1" and bool(root["islands"]) == reads
    # Made again: the same bytes (put_new refuses other bytes under a written key).
    assert views.publish(st, pack, first) == keys

    # The next manifest starts from this one's layout: with the same rows nothing moves.
    _, second = published(pack_dir, st, 2)
    [key] = views.publish(st, pack, second)
    after = json.loads(st.get(key))
    assert after["previous"] == {"manifest": first, "sha256": views.sha256(st.get(keys[0]))}
    assert {k: s["layout"]["sha256"] for k, s in after["sheets"].items()} == {k: s["layout"]["sha256"] for k, s in index["sheets"].items()}
    # A full relayout is a choice of its own, and says so.
    relaid = dict(views.plan(st, pack, second, relayout=True))[key]
    assert json.loads(relaid)["relayout"] is True and "previous" not in json.loads(relaid)


def test_a_role_whose_view_fails_its_check_gets_no_index_and_the_others_do(tmp_path, monkeypatch):
    """Roles in order: the first role's views fail, so it gets no view index; the second role's views depend
    only on its own rows and are written. The run still says it was blocked."""
    st = store.FileStore(tmp_path / "store")
    e = batch.epoch(PACKS[0], epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    try:
        mid = publish.publish(e, st, ROLES | {"propose": "may_read"})["id"]
    except publish.Blocked:
        pytest.skip("a red pack publishes nothing, so it has no views")
    real, calls = views.check_islands, []

    def first_fails(*a):
        calls.append(a[0])
        return ["root: island k.secret counts an element the role does not read"] if len(calls) == 1 else real(*a)

    monkeypatch.setattr(views, "check_islands", first_fails)
    with pytest.raises(views.Blocked):
        views.publish(st, e.pack, mid)
    assert st.get(views.index_key(e.pack, mid, "propose")) is None
    assert not [k for k in st.list(f"{e.pack}/{mid}/propose/views/")], "a failed role writes nothing"
    assert st.get(views.index_key(e.pack, mid, "viewer")) is not None


def test_roles_with_the_same_layout_inputs_lay_out_once_and_each_is_checked(tmp_path, monkeypatch):
    """Two filtered roles that read the same rows: the Node entry runs once, both get the same pieces under
    their own keys, and every check runs for each role on its own rows."""
    st = store.FileStore(tmp_path / "store")
    e = batch.epoch(PACKS[0], epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "test")])
    try:
        mid = publish.publish(e, st, ROLES | {"propose": "may_read"})["id"]
    except publish.Blocked:
        pytest.skip("a red pack publishes nothing, so it has no views")
    m = json.loads(st.get(f"{e.pack}/manifests/{mid}.json"))
    of = lambda role: sorted((s["relation"], s["sha256"]) for s in m["snapshots"] if s["role"] == role)
    if of("propose") != of("viewer"):
        pytest.skip("the roles read different rows")
    laid, checked = [], []
    real_lay_out, real_check = views._lay_out, views.check_islands
    monkeypatch.setattr(views, "_lay_out", lambda *a: laid.append(a[5]) or real_lay_out(*a))
    monkeypatch.setattr(views, "check_islands", lambda snapshots, *a: checked.append(snapshots) or real_check(snapshots, *a))
    views.publish(st, e.pack, mid)
    assert laid == ["propose"] and len(checked) == 2
    index = lambda role: json.loads(st.get(views.index_key(e.pack, mid, role)))
    shas = lambda i: ({k: s["layout"]["sha256"] for k, s in i["sheets"].items()}, {k: p["sha256"] for k, p in i["islands"].items()},
                      i["page"]["sha256"])
    assert shas(index("propose")) == shas(index("viewer"))
    assert index("propose")["page"]["uri"] != index("viewer")["page"]["uri"], "each role's pieces under its own key"


def test_the_layout_key_names_every_layout_input():
    bundle = {"sha256": "b"}
    mine = [{"relation": "k", "sha256": "1"}]
    key = views._layout_key(bundle, mine, {"map": b"{}"})
    assert key == views._layout_key(dict(bundle), [dict(mine[0], role="other", uri="s3://x/other")], {"map": b"{}"})
    assert key != views._layout_key({"sha256": "c"}, mine, {"map": b"{}"})
    assert key != views._layout_key(bundle, [{"relation": "k", "sha256": "2"}], {"map": b"{}"})
    assert key != views._layout_key(bundle, mine, {"map": b"[]"})
    assert key != views._layout_key(bundle, mine, {})


def test_views_are_made_for_main_manifests_only(tmp_path):
    with pytest.raises(ValueError):
        views.plan(store.FileStore(tmp_path), "pack", "p-1")


@pytest.mark.parametrize("pack_dir", PACKS[:1], ids=lambda p: p.relative_to(ROOT / "examples").as_posix())
def test_the_page_index_lists_what_the_role_reads(pack_dir, tmp_path):
    st = store.FileStore(tmp_path / "store")
    pack, first = published(pack_dir, st, 1)
    [key] = views.publish(st, pack, first)
    index = json.loads(st.get(key))
    page = json.loads(st.get(views.key_of(index["page"]["uri"])))
    assert page["format"] == "rede.page/2" and page["title"] and page["sheets"] == sorted(["map", *(k for k in index["sheets"] if k.startswith(("flow.", "matrix.")))])
    for k in page["kinds"]:
        ids = [r["id"] for r in k["first"]]
        assert ids == sorted(ids) and len(ids) <= min(k["count"], 25)


def test_order_metric_measures_actual_compiler_snapshot_flow_enum_order(tmp_path):
    """Actual producers and raw cells: independently measured compiled enum order."""
    from dataclasses import replace
    import yaml
    from rezono_checker.semiotic_order import lane_order
    from rezono_checker.views import Role

    target = tmp_path / "minimal"
    shutil.copytree(ROOT / "compiler/tests/fixtures/minimal", target)
    values = ["zeta", "alpha", "middle"]
    schema_path = target / "schema/minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text())
    schema["enums"]["State"]["permissible_values"] = {v: {} for v in values}
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False))
    labels_path = target / "labels/nl.yaml"
    labels = {k: v for k, v in yaml.safe_load(labels_path.read_text()).items() if not k.startswith("state.")}
    labels.update({f"state.{v}": v for v in values})
    labels_path.write_text(yaml.safe_dump(labels, sort_keys=False))
    channels_path = target / "channels.yaml"
    channels = yaml.safe_load(channels_path.read_text())
    channels["flows"] = [{"id": "enum_order", "title_message": "path_equation", "direction": "right",
                          "nodes": [{"kind": "beta", "lane": {"channel": "lane", "slot": "beta.state", "level": "ordered",
                                                                "meaning_message": "path_equation"}}, {"kind": "alpha"}],
                          "edges": [{"arrow": "beta.alpha"}]}]
    channels_path.write_text(yaml.safe_dump(channels, sort_keys=False))
    (target / "facts").mkdir(exist_ok=True)
    (target / "facts/one.yaml").write_text(yaml.safe_dump({"alpha": [{"id": "a", "title": "anchor", "size": 1}],
        "beta": [{"id": f"b-{v}", "alpha": "a", "state": v} for v in values]}, sort_keys=False))
    (target / "rules").mkdir(exist_ok=True)
    (target / "rules/access.dl").write_text('.decl may_read(role: symbol, kind: symbol, element: symbol)\n'
        'may_read("viewer", "alpha", x) :- alpha(x).\nmay_read("viewer", "beta", x) :- beta(x).\n.output may_read\n')
    st = store.FileStore(tmp_path / "store")
    prepared = views.prepare(st, "minimal", "m-1", ["viewer"])
    epoch = batch.epoch(target, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "synthetic-test")])
    epoch = replace(epoch, build=epoch.build | {"views": prepared.component})
    manifest = publish.publish(epoch, st, ROLES)
    [index_key] = views.publish(st, "minimal", manifest["id"], prepared=prepared)
    index = json.loads(st.get(index_key))
    compiled_ref = next(c for c in manifest["compiled"] if c["file"] == "bundle/schema-bundle.json")
    compiled = json.loads(st.get(views.key_of(compiled_ref["uri"])))
    snapshots = {s["relation"]: st.get(views.key_of(s["uri"])) for s in manifest["snapshots"] if s["role"] == "viewer"}
    assert {r["key"][1] for r in json.loads(snapshots["beta__state"])} == set(values)
    assert set(next(e for e in compiled["enums"] if e["id"] == "state")["values"]) == {f"state.{v}" for v in values}
    sheet = index["sheets"]["flow.enum_order"]
    prefix = "minimal/m-1/viewer/views/"
    root_key, layout_key = (views.key_of(sheet[k]["uri"]) for k in ("root", "layout"))
    tiles = {k.removeprefix(prefix): st.get(k) for k in st.list(prefix + "flow.enum_order/") if k != layout_key}
    # A sheet with lanes has a level above its nodes, also when it fits one tile (RV-U08; docs/gui.md, "Overview
    # by lane"): the root tile holds the overview by lane, and the nodes are on the last level.
    root = json.loads(st.get(root_key))
    assert sheet["levels"] == 2 and "nodes" not in root
    # One lane per enum value of `beta.state`, and the lane of the kind without a lane binding (`alpha`).
    assert {x["lane"] for x in root["overview"]["lanes"]} == {*(f"enum:state:{v}" for v in values), "kind:alpha"}
    last = [t for t in map(json.loads, tiles.values()) if t["level"] == sheet["levels"] - 1]
    beta = list({n["id"]: n for t in last for n in t["nodes"] if n["id"].startswith("beta/")}.values())
    assert len(beta) == 3 and all(n["status"] == "valid" for n in beta)
    for value in values:
        assert sum(n["lane"] == {"relation": "beta__state", "value": value} for n in beta) == 1
    result = lane_order("flow.enum_order", "beta", Role(snapshots, compiled), st.get(layout_key), tiles,
                        root_key.removeprefix(prefix), sheet["tile"], sheet["fanout"], sheet["levels"])
    assert (result.state, result.reason, result.eligible, result.preserved) == ("measured", None, 3, 3)
