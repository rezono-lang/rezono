"""C3 view inputs: capture history once, keep roles separate, and refuse another implementation."""

from collections import Counter
from dataclasses import replace
import json
import shutil

import pytest
from rezono_canon import canonical_bytes

from rezono_publisher import store, view_build, views


class History:
    def __init__(self):
        self.data, self.reads = {}, Counter()

    def uri(self, key):
        return f"s3://test/{key}"

    def put_new(self, key, body):
        if key in self.data and self.data[key] != body:
            raise store.Conflict(key)
        self.data[key] = body

    def get(self, key):
        self.reads[key] += 1
        return self.data.get(key)

    def list(self, prefix):
        self.reads["list:" + prefix] += 1
        return sorted(k for k in self.data if k.startswith(prefix))


def old_view(st, mid, role, layout):
    key = f"p/{mid}/{role}/views/map/layout.json"
    st.data[key] = layout
    index = {"pack": "p", "manifest": mid, "role": role, "sheets": {
        "map": {"layout": {"uri": st.uri(key), "sha256": views.sha256(layout)}}}}
    st.data[views.index_key("p", mid, role)] = views.dumps(index)
    st.data[f"p/manifests/{mid}.json"] = b"{}"


@pytest.fixture
def identity(monkeypatch, tmp_path):
    tree = source_tree(tmp_path / "view-build")
    inventory = view_build.inventory

    def source_inventory(root=view_build.ROOT):
        return inventory(tree if root == view_build.ROOT else root)

    monkeypatch.setattr(view_build, "inventory", source_inventory)
    monkeypatch.setattr(view_build, "executable", lambda node=None: "/node")
    monkeypatch.setattr(view_build, "runtime", lambda node, expected=None: {"executable_sha256": "a" * 64,
                        "version": "v24.0.0", "platform": "linux", "architecture": "x64", "versions": []})


def current(st, prepared, roles=("a", "b")):
    st.data["p/bundle.json"] = b"{}"
    record = views.dumps({"views": prepared.component})
    st.data["p/build.json"] = record
    snapshots = []
    for role in roles:
        key = f"p/m-2/{role}/rows.json"
        st.data[key] = views.dumps([[role + "-public"]])
        snapshots.append({"role": role, "complete": False, "relation": "item", "uri": st.uri(key),
                          "sha256": views.sha256(st.data[key])})
    m = {"id": "m-2", "build": {"uri": st.uri("p/build.json"), "sha256": views.sha256(record)},
         "compiled": [{"file": "bundle/schema-bundle.json", "uri": st.uri("p/bundle.json"), "sha256": views.sha256(b"{}")}],
         "snapshots": snapshots}
    st.data["p/manifests/m-2.json"] = views.dumps(m)


def renderer(monkeypatch, calls):
    def layout(st, pack, mid, raw, bundle, role, mine, snapshots, layouts, node):
        # A revoked old element can affect only positioning, never the current input rows or a foreign role.
        assert json.loads(snapshots["item"]) == [[role + "-public"]]
        calls.append((role, dict(layouts), node))
        return {}, {}

    def checked(st, pack, mid, m, role, relayout, mine, snapshots, start, summary, made):
        index = {"pack": pack, "manifest": mid, "role": role, "relayout": relayout, "sheets": {},
                 "sources": [{"relation": s["relation"], "sha256": s["sha256"]} for s in mine]}
        if start:
            index["previous"] = start
        return [(views.index_key(pack, mid, role), views.dumps(index))]

    monkeypatch.setattr(views, "_lay_out", layout)
    monkeypatch.setattr(views, "_checked", checked)


def test_render_uses_frozen_role_inputs_after_history_changes(identity, monkeypatch):
    st, calls = History(), []
    old_view(st, "m-1", "a", b'{"revoked":"a-secret"}')
    old_view(st, "m-1", "b", b'{"revoked":"b-secret"}')
    prepared = views.prepare(st, "p", "m-2", ["b", "a"])
    assert st.reads["list:p/manifests/"] == 2
    # Change both the chosen bytes and the apparent history after capture. Neither is read again.
    st.data["p/m-1/a/views/map/layout.json"] = b"changed"
    old_view(st, "m-0", "a", b"other")
    current(st, prepared)
    before = st.reads.copy()
    monkeypatch.setattr(views, "previous", lambda *a: pytest.fail("history rediscovered during render"))
    renderer(monkeypatch, calls)
    result = views.plan(st, "p", "m-2", prepared=prepared)
    assert calls == [("a", {"map": b'{"revoked":"a-secret"}'}, "/node"),
                     ("b", {"map": b'{"revoked":"b-secret"}'}, "/node")]
    assert st.reads["p/m-1/a/views/map/layout.json"] == before["p/m-1/a/views/map/layout.json"]
    assert st.reads["list:p/manifests/"] == before["list:p/manifests/"]
    for _, body in result:
        index = json.loads(body)
        assert index["capture_sha256"] == prepared.capture(index["role"]).sha256
        assert b"secret" not in body and b"revoked" not in body
    assert b"secret" not in prepared.component_bytes and b"capture" not in prepared.component_bytes


def test_retry_keeps_the_first_choice_instead_of_a_newer_older_index(identity, monkeypatch):
    st, calls = History(), []
    old_view(st, "m-0", "a", b"first")
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("a",))
    renderer(monkeypatch, calls)
    views.publish(st, "p", "m-2", prepared=prepared)
    old_view(st, "m-1", "a", b"arrived later")
    again = views.prepare(st, "p", "m-2", ["a"])
    assert again.capture("a") == prepared.capture("a")
    immutable = dict(st.data)
    views.publish(st, "p", "m-2", prepared=again)
    assert st.data == immutable


def test_missing_previous_is_an_explicit_capture_not_a_late_lookup(identity, monkeypatch):
    st, calls = History(), []
    prepared = views.prepare(st, "p", "m-2", ["a"])
    old_view(st, "m-1", "a", b"too late")
    current(st, prepared, ("a",))
    renderer(monkeypatch, calls)
    views.publish(st, "p", "m-2", prepared=prepared)
    assert calls == [("a", {}, "/node")]
    assert "previous" not in json.loads(st.data[views.index_key("p", "m-2", "a")])
    assert views.prepare(st, "p", "m-2", ["a"]).capture("a").previous == ""


@pytest.mark.parametrize("wrong", ["index", "layout"])
def test_capture_refuses_foreign_role_history(identity, wrong):
    st = History()
    old_view(st, "m-1", "a", b"private")
    key = views.index_key("p", "m-1", "a")
    d = json.loads(st.data[key])
    if wrong == "index":
        d["role"] = "b"
    else:
        d["sheets"]["map"]["layout"]["uri"] = st.uri("p/m-1/b/views/map/layout.json")
    st.data[key] = views.dumps(d)
    with pytest.raises(ValueError, match="another role"):
        views.prepare(st, "p", "m-2", ["a"])


def source_tree(tmp_path):
    for path in ("viewer/scripts/views.ts", "viewer/src/lib/layout/map.ts", "viewer/package.json",
                 "viewer/package-lock.json", "packs/std-view/palette.yaml", "packs/std-view/messages/en.mf2"):
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("original", encoding="utf-8")
    return tmp_path


def test_inventory_orders_by_relative_posix_path_text(tmp_path):
    root = source_tree(tmp_path)
    (root / "viewer/src/lib/layout.ts").write_text("original", encoding="utf-8")

    paths = [entry["path"] for entry in view_build.inventory(root)]
    assert paths == sorted(paths)


@pytest.mark.parametrize("path", ["viewer/scripts/views.ts", "viewer/src/lib/layout/map.ts",
                                   "viewer/package.json", "viewer/package-lock.json",
                                   "packs/std-view/messages/en.mf2"])
def test_source_and_lock_mismatch_refused_before_node(identity, tmp_path, monkeypatch, path):
    root, inventory = source_tree(tmp_path), view_build.inventory
    monkeypatch.setattr(view_build, "inventory", lambda *a: inventory(root))
    st = History()
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("a",))
    (root / path).write_text("changed", encoding="utf-8")
    monkeypatch.setattr(view_build, "runtime", lambda *a: pytest.fail("Node started after source mismatch"))
    monkeypatch.setattr(views, "_lay_out", lambda *a: pytest.fail("layout ran after source mismatch"))
    with pytest.raises(ValueError, match="source or npm lock"):
        views.publish(st, "p", "m-2", prepared=prepared)


def test_changed_node_binary_is_refused_before_execution(tmp_path, monkeypatch):
    binary = tmp_path / "node"
    binary.write_bytes(b"replacement")
    monkeypatch.setattr(view_build.subprocess, "run", lambda *a, **k: pytest.fail("replacement Node executed"))
    with pytest.raises(ValueError, match="Node executable differs"):
        view_build.runtime(str(binary), {"executable_sha256": "0" * 64})


def test_runtime_version_mismatch_blocks_render(identity, monkeypatch):
    st = History()
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("a",))
    real = view_build.runtime
    monkeypatch.setattr(view_build, "runtime", lambda *a: real(*a) | {"version": "v99"})
    monkeypatch.setattr(views, "_lay_out", lambda *a: pytest.fail("layout ran after runtime mismatch"))
    with pytest.raises(ValueError, match="Node runtime differs"):
        views.publish(st, "p", "m-2", prepared=prepared)


def test_no_foreign_or_missing_prepared_role_can_render(identity, monkeypatch):
    st = History()
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("b",))
    monkeypatch.setattr(views, "_lay_out", lambda *a: pytest.fail("foreign role rendered"))
    with pytest.raises(ValueError, match="private input checkpoint"):
        views.publish(st, "p", "m-2", prepared=prepared)
    bad = replace(prepared, captures=(replace(prepared.capture("a"), pack="other"),))
    with pytest.raises(ValueError, match="unique prepared inputs"):
        bad.capture("a")


def test_node_injection_environment_does_not_reach_layout(monkeypatch):
    for key in ("NODE_OPTIONS", "NODE_PATH", "NODE_ICU_DATA", "node_options"):
        monkeypatch.setenv(key, "injection")
    assert not any(k.upper().startswith("NODE_") for k in view_build.node_env())


def test_legacy_views_without_build_identity_keep_the_existing_path(monkeypatch):
    st = History()
    fake = view_build.PreparedViews(canonical_bytes({}), "/node", "p", "m-2", ())
    current(st, fake, ("a",))
    m = json.loads(st.data["p/manifests/m-2.json"])
    del m["build"]
    st.data["p/manifests/m-2.json"] = views.dumps(m)
    calls = []
    renderer(monkeypatch, calls)
    monkeypatch.setattr(view_build, "component", lambda *a: pytest.fail("legacy view requires no component"))
    result = views.plan(st, "p", "m-2")
    assert "capture_sha256" not in json.loads(result[-1][1])


@pytest.mark.parametrize(
    "with_views",
    [False, True],
)
def test_cli_build_identity_is_final_before_manifest_and_viewless_needs_no_node(identity, monkeypatch, with_views):
    from rezono_publisher import __main__ as cli, batch
    from test_publish import epoch

    st, called = History(), []
    manifest = "p/manifests/m-2.json"
    monkeypatch.setattr(batch, "epoch", lambda *a, **k: epoch(pack="p", epoch=2, build={"format": "rezono.build/3"}))
    monkeypatch.setattr(cli.store, "open_store", lambda *a: st)
    write = st.put_new

    def build_of(raw):
        key = views.key_of(json.loads(raw)["build"]["uri"])
        return json.loads(st.data[key])

    def put(key, body):
        if key == manifest:
            assert ("views" in build_of(body)) is with_views
            called.append("manifest")
        write(key, body)

    def render(st, pack, mid, *, prepared, manifest_bytes):
        assert manifest not in st.data
        assert prepared.capture("guest").previous == ""
        component = build_of(manifest_bytes)["views"]
        assert component == prepared.component
        assert "layouts" not in component and "captures" not in component
        called.append("views")

    monkeypatch.setattr(st, "put_new", put)
    monkeypatch.setattr(cli.views, "publish", render)
    if not with_views:
        monkeypatch.setattr(cli.views, "prepare", lambda *a: pytest.fail("viewless publication called Node"))
    args = ["p", "--store", "file://unused", "--role", "guest=may_read", "--epoch", "2",
            "--knowledge-time", "2026-01-01T00:00:00Z"]
    assert cli.main(args + (["--views"] if with_views else [])) == 0
    assert called == (["views", "manifest"] if with_views else ["manifest"])


def test_restart_after_fixed_manifest_keeps_frozen_none_despite_late_history(identity, monkeypatch):
    st, calls = History(), []
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("a",))  # Crash here: manifest exists, target role index does not.
    original_hash = prepared.capture("a").sha256
    del prepared
    old_view(st, "m-1", "a", b"arrived after crash")
    monkeypatch.setattr(views, "previous", lambda *a: pytest.fail("restart rediscovered history"))
    renderer(monkeypatch, calls)
    views.publish(st, "p", "m-2")  # No in-memory prepared object survives the restart.
    assert calls == [("a", {}, "/node")]
    index = json.loads(st.data[views.index_key("p", "m-2", "a")])
    assert index["capture_sha256"] == original_hash and "previous" not in index


@pytest.mark.parametrize("damage", ["missing", "json", "role", "mode", "payload"])
def test_fixed_main_refuses_missing_or_damaged_private_checkpoint(identity, monkeypatch, damage):
    st = History()
    old_view(st, "m-1", "a", b"original")
    prepared = views.prepare(st, "p", "m-2", ["a"])
    current(st, prepared, ("a",))
    key = views.checkpoint_key("p", "m-2", "a")
    if damage == "missing":
        del st.data[key]
    elif damage == "json":
        st.data[key] = b"corrupt"
    else:
        d = json.loads(st.data[key])
        if damage == "role":
            d["capture"]["role"] = "other"
        elif damage == "mode":
            d["capture"]["relayout"] = True
        else:
            d["layouts"][0]["bytes"] = "Y2hhbmdlZA=="
        st.data[key] = views.dumps(d)
    monkeypatch.setattr(views, "previous", lambda *a: pytest.fail("fixed main tried a fallback capture"))
    monkeypatch.setattr(views, "_lay_out", lambda *a: pytest.fail("damaged inputs rendered"))
    with pytest.raises(ValueError, match="private input checkpoint"):
        views.publish(st, "p", "m-2")


def test_concurrent_preparer_uses_first_committed_capture(identity, monkeypatch):
    st = History()
    old_view(st, "m-1", "a", b"candidate")
    # The competing winner had captured the absence of any history before this candidate.
    first = view_build.CapturedRole("p", "m-2", "a", False)
    real = st.put_new

    def race(key, body):
        if key == views.checkpoint_key("p", "m-2", "a"):
            component = json.loads(body)["build"]
            real(key, first.checkpoint(component))
        real(key, body)  # Conditional put now conflicts; prepare must load, never overwrite, the winner.

    monkeypatch.setattr(st, "put_new", race)
    prepared = views.prepare(st, "p", "m-2", ["a"])
    assert prepared.capture("a") == first
    assert json.loads(st.data[views.checkpoint_key("p", "m-2", "a")])["capture"]["layouts"] == []


@pytest.mark.parametrize("failure", ["check", "index", "manifest", "head"])
def test_cli_restart_recovers_frozen_checkpoint(identity, monkeypatch, failure):
    from rezono_publisher import __main__ as cli, batch, pointers, publish
    from test_publish import epoch

    st, calls = History(), []
    roles = {"guest": "may_read"}
    publish.publish(epoch(pack="p"), st, roles)
    old_manifest = "p/manifests/m-1.json"
    index = views.index_key("p", "m-2", "guest")
    manifest = "p/manifests/m-2.json"
    head = pointers.head_key("p", 2)
    target = {"index": index, "manifest": manifest, "head": head}.get(failure)
    stopped = True
    monkeypatch.setattr(batch, "epoch", lambda *a, **k: epoch(pack="p", epoch=2, build={"format": "rezono.build/3"}))
    monkeypatch.setattr(cli.store, "open_store", lambda *a: st)

    def layout(st, pack, mid, raw, bundle, role, mine, snapshots, layouts, node):
        assert (pack, mid, role, node) == ("p", "m-2", "guest", "/node")
        assert "node" in snapshots and layouts == {}
        calls.append(raw)
        return {}, {}

    def checked(st, pack, mid, m, role, relayout, mine, snapshots, start, summary, made):
        assert start is None
        if stopped and failure == "check":
            raise views.Blocked("fixture check failed")
        return [(index, views.dumps({"pack": pack, "manifest": mid, "role": role, "relayout": relayout}))]

    monkeypatch.setattr(views, "_lay_out", layout)
    monkeypatch.setattr(views, "_checked", checked)
    write = st.put_new

    def interrupted(key, body):
        if key == target:
            raise store.Conflict(key)
        write(key, body)

    monkeypatch.setattr(st, "put_new", interrupted)
    args = ["p", "--store", "file://unused", "--role", "guest=may_read", "--epoch", "2",
            "--knowledge-time", "2026-01-01T00:00:00Z", "--views"]
    assert cli.main(args) == (2 if failure == "check" else 1)
    assert (index in st.data) is (failure in ("manifest", "head"))
    assert (manifest in st.data) is (failure == "head")
    assert head not in st.data
    assert st.list("p/heads/") == [pointers.head_key("p", 1)]

    monkeypatch.setattr(st, "put_new", write)
    assert pointers.backfill(st, "p") == ([head] if failure == "head" else [])
    old_bytes = st.data[old_manifest]
    old_view(st, "m-1", "guest", b"late layout")
    st.data[old_manifest] = old_bytes
    before_retry = dict(st.data)
    monkeypatch.setattr(views, "previous", lambda *a: pytest.fail("CLI restart discovered a new predecessor"))
    stopped = False
    assert cli.main(args) == 0
    assert calls == [st.data[manifest]] * 2
    assert all(st.data[key] == body for key, body in before_retry.items())
    assert st.list("p/heads/") == [head, pointers.head_key("p", 1)]


@pytest.mark.skipif(not shutil.which("node") or not (view_build.ROOT / "viewer/node_modules").is_dir(),
                    reason="needs Node and the viewer's locked dependencies")
def test_real_node_and_checker_remove_a_revoked_node_while_using_captured_previous_layout(monkeypatch):
    """Three authored nodes, then two: exercise views.ts and every real view checker, without an engine."""
    from rezono_compiler import emit, pack
    from rezono_publisher.publish import snapshot

    model = pack.read(view_build.ROOT / "compiler/tests/fixtures/minimal")
    bundle = emit.compile_pack(model)["bundle/schema-bundle.json"].encode()
    st = History()
    st.put_new("minimal/bundle.json", bundle)

    def main(mid, ids, prepared):
        record = views.dumps({"views": prepared.component})
        build_key = f"minimal/builds/{views.sha256(record)}.json"
        st.put_new(build_key, record)
        # Authoritative role-filtered snapshots: reader loses the middle node at epoch two.
        data = {"alpha": [(i,) for i in ids], "alpha__title": [(i, i) for i in ids],
                "alpha__size": [(i, 1) for i in ids]}
        snapshots = []
        for relation, rows in data.items():
            body = snapshot(rows)
            key = f"minimal/{mid}/reader/relations/{relation}.json"
            st.put_new(key, body)
            snapshots.append({"role": "reader", "relation": relation, "complete": False, "full": False,
                              "uri": st.uri(key), "sha256": views.sha256(body)})
        m = {"id": mid, "epoch": int(mid[2:]), "knowledge_time": "2026-01-01T00:00:00Z",
             "snapshots": snapshots, "compiled": [{"file": "bundle/schema-bundle.json",
             "uri": st.uri("minimal/bundle.json"), "sha256": views.sha256(bundle)}],
             "build": {"uri": st.uri(build_key), "sha256": views.sha256(record)}}
        st.put_new(f"minimal/manifests/{mid}.json", views.dumps(m))

    first = views.prepare(st, "minimal", "m-1", ["reader"])
    main("m-1", ["keep-a", "revoked-node", "keep-c"], first)
    [index_key] = views.publish(st, "minimal", "m-1", prepared=first)
    old_index = json.loads(st.data[index_key])
    old_layout_key = views.key_of(old_index["sheets"]["map"]["layout"]["uri"])
    assert b"revoked-node" in st.data[old_layout_key]

    second = views.prepare(st, "minimal", "m-2", ["reader"])
    captured = second.capture("reader")
    assert b"revoked-node" in dict(captured.layouts)["map"]
    checkpoint_key = views.checkpoint_key("minimal", "m-2", "reader")
    checkpoint_bytes = st.data[checkpoint_key]
    # The real renderer must consume the committed capture, even if history changes after preparation.
    before = st.reads[old_layout_key]
    st.data[old_layout_key] = b"mutated history must not be fetched"
    monkeypatch.setattr(views, "previous", lambda *a: pytest.fail("real render rediscovered history"))
    main("m-2", ["keep-a", "keep-c"], second)
    [new_key] = views.publish(st, "minimal", "m-2", prepared=second)
    assert st.reads[old_layout_key] == before
    assert st.data[checkpoint_key] == checkpoint_bytes
    index = json.loads(st.data[new_key])
    assert index["capture_sha256"] == captured.sha256
    layout = json.loads(st.data[views.key_of(index["sheets"]["map"]["layout"]["uri"])])
    assert set(layout["nodes"]) == {"alpha/keep-a", "alpha/keep-c"}
    shown = [body for key, body in st.data.items() if key.startswith("minimal/m-2/reader/views/")]
    assert shown and all(b"revoked-node" not in body for body in shown)
