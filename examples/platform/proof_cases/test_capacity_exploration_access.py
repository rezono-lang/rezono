"""Fail-closed role access and DuckDB cleanup regression tests for capacity exploration."""

from __future__ import annotations

import importlib.util
import json
import shutil
from types import SimpleNamespace

import pytest
import yaml

from case_support import ROOT
from rezono_publisher import access, pointers, publish, store


def _load_capacity_exploration():
    runner = ROOT / "portal" / "capacity_exploration.py"
    spec = importlib.util.spec_from_file_location("capacity_exploration_access_test", runner)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _build_scenario(path, values):
    import sys

    sys.path.insert(0, str(ROOT))
    try:
        from request_preview import request_rows
    finally:
        sys.path.pop(0)

    model = path / "examples" / "platform"
    shutil.copytree(ROOT, model, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(ROOT.parents[1] / "packs", path / "packs")
    teams = model / "teams"
    third = teams / "reed/fern" / "request.json"
    third.parent.mkdir()
    third.write_text(
        json.dumps(
            dict(
                profile="production",
                items={"cluster": "medium"},
                connections=[],
                submittedAt="2026-01-03T00:00:00Z",
            )
        ),
        encoding="utf-8",
    )
    catalog = json.loads((model / "tenant-catalog.json").read_text(encoding="utf-8"))
    rec = dict(request_rows(teams, catalog))
    rec["offered_cores"] = [
        dict(id=f"{item}/{size}", cores=x[0])
        for item, options in catalog["catalog"].items()
        for size, x in options["sizes"].items()
    ]
    rec["pool_cores"] = [{"id": "pool", "cores": 6}]
    rec["outbound_approval"] = [{"id": "permit", "connection": "elm/ledger/1"}]
    rec["capacity_exploration"] = [
        {"id": "fern-grid", "pool": "pool", "request": "reed/fern", "values": values}
    ]
    (model / "facts" / "capacity-grid.yaml").write_text(yaml.safe_dump(rec), encoding="utf-8")
    return model


def _write_base_manifest(bucket: store.FileStore, pack: str, snapshots: list[dict]) -> dict:
    manifest = {
        "id": "m-1",
        "epoch": 1,
        "knowledge_time": "2026-02-01T00:00:00Z",
        "snapshots": snapshots,
    }
    data = publish.canonical(manifest)
    bucket.put_new(f"{pack}/manifests/m-1.json", data)
    pointers.write(bucket, pack, "manifests", data)
    return manifest


def test_role_mode_blocks_unpublished_and_escalated_roles_with_base():
    mod = _load_capacity_exploration()
    base = {
        "id": "m-1",
        "snapshots": [
            {"relation": "request", "role": "elm", "complete": False},
            {"relation": "quota", "role": "elm", "complete": False},
        ],
    }

    assert mod._role_mode(base, "elm") == access.FILTERED
    assert mod._role_mode(base, "elm", role_mode=access.FILTERED) == access.FILTERED

    with pytest.raises(publish.Blocked, match="not published in m-1"):
        mod._role_mode(base, "revoked")
    with pytest.raises(publish.Blocked, match="not published in m-1"):
        mod._role_mode(base, "operator")
    with pytest.raises(publish.Blocked, match="not published in m-1"):
        mod._role_mode(base, "revoked", role_mode=access.COMPLETE)
    with pytest.raises(publish.Blocked, match="does not match m-1"):
        mod._role_mode(base, "elm", role_mode=access.COMPLETE)

    inconsistent = {
        "id": "m-2",
        "snapshots": [
            {"relation": "request", "role": "elm", "complete": False},
            {"relation": "quota", "role": "elm", "complete": True},
        ],
    }
    with pytest.raises(publish.Blocked, match="inconsistent access modes"):
        mod._role_mode(inconsistent, "elm")


def test_role_mode_without_base_fails_closed_for_filtered_roles():
    mod = _load_capacity_exploration()
    tables = {
        "role": [("elm",), ("reed",)],
        "role__capability": [("elm", "read"), ("reed", "read")],
    }
    prog = SimpleNamespace(
        rules={
            "r1": SimpleNamespace(
                head=SimpleNamespace(relation="may_read", terms=("platform-catalogue", "product", "?p"))
            )
        }
    )

    for role in ("elm", "reed", "platform-catalogue", "guest", "unknown"):
        assert mod._role_mode(None, role, tables=tables, prog=prog) == access.FILTERED

    assert mod._role_mode(None, "operator", tables=tables, prog=prog) == access.COMPLETE
    assert mod._role_mode(None, "operator", role_mode=access.FILTERED, tables=tables, prog=prog) == access.FILTERED
    assert mod._role_mode(None, "checker", role_mode=access.COMPLETE, tables=tables, prog=prog) == access.COMPLETE

    operator_declared = {"role": [("operator",)]}
    assert mod._role_mode(None, "operator", tables=operator_declared, prog=prog) == access.FILTERED

    with pytest.raises(ValueError, match="unknown role_mode"):
        mod._role_mode(None, "operator", role_mode="admin")


def test_publish_exploration_blocks_role_missing_from_base_manifest(tmp_path):
    mod = _load_capacity_exploration()
    model = _build_scenario(tmp_path, [10])
    bucket = store.FileStore(tmp_path / "published")
    _write_base_manifest(
        bucket,
        "platform-core",
        [{"relation": "request", "role": "elm", "complete": False}],
    )
    before_keys = list(bucket.list(""))

    for unauthorized in ("revoked-role", "operator"):
        with pytest.raises(publish.Blocked, match="not published in m-1"):
            mod.publish_exploration(model, bucket, "fern-grid", unauthorized)

    assert list(bucket.list("")) == before_keys


def test_publish_exploration_without_base_never_grants_complete_to_filtered_role(tmp_path):
    mod = _load_capacity_exploration()
    model = _build_scenario(tmp_path, [10])
    bucket = store.FileStore(tmp_path / "published")

    with pytest.raises((ValueError, KeyError, publish.Blocked)):
        mod.publish_exploration(model, bucket, "fern-grid", "elm")

    assert list(bucket.list("platform-core/explorations/")) == []
    for manifest_key in bucket.list("platform-core/manifests/"):
        manifest = json.loads(bucket.get(manifest_key))
        elm_snaps = [s for s in manifest.get("snapshots", ()) if s.get("role") == "elm"]
        assert elm_snaps
        assert all(s.get("complete") is False for s in elm_snaps)


def test_calc_only_candidate_closes_both_duckdb_connections(tmp_path, monkeypatch):
    mod = _load_capacity_exploration()

    class _FakeConnection:
        def __init__(self):
            self.closed = False

        def execute(self, _sql):
            return self

        def executemany(self, _sql, _rows):
            return self

        def close(self):
            self.closed = True

    created: list[_FakeConnection] = []

    def fake_connect():
        conn = _FakeConnection()
        created.append(conn)
        return conn

    monkeypatch.setattr(mod.duckdb, "connect", fake_connect)
    monkeypatch.setattr(mod.provenance, "collected", lambda entries: [])
    monkeypatch.setattr(
        mod.batch,
        "origin_check",
        lambda model, fact_sources, copied: {"name": "rezono:origin", "status": "green", "violations": 0},
    )
    monkeypatch.setattr(mod.batch, "tree_sha256", lambda copied: "0" * 64)

    seen_conns: list[tuple[_FakeConnection, _FakeConnection]] = []

    def fake_calculate(_calc_program, calc_db, rule_db, _rows):
        seen_conns.append((calc_db, rule_db))
        assert not calc_db.closed and not rule_db.closed
        return []

    monkeypatch.setattr(mod.batch, "calculate", fake_calculate)

    mod._run_rules_for_candidate(
        model=SimpleNamespace(),
        prog=None,
        calc_program=object(),
        db_rows={},
        facts={},
        checks=[],
        copied=tmp_path,
        changed_files=set(),
        base_sources_by_file={},
        params={},
        tables_sql="",
    )

    assert len(created) == 2
    assert len(seen_conns) == 1
    assert seen_conns[0][0] is not seen_conns[0][1]
    assert all(conn.closed for conn in created)

    created.clear()

    def failing_calculate(_calc_program, _calc_db, _rule_db, _rows):
        raise RuntimeError("boom")

    monkeypatch.setattr(mod.batch, "calculate", failing_calculate)

    with pytest.raises(RuntimeError, match="boom"):
        mod._run_rules_for_candidate(
            model=SimpleNamespace(),
            prog=None,
            calc_program=object(),
            db_rows={},
            facts={},
            checks=[],
            copied=tmp_path,
            changed_files=set(),
            base_sources_by_file={},
            params={},
            tables_sql="",
        )

    assert len(created) == 2
    assert all(conn.closed for conn in created)
