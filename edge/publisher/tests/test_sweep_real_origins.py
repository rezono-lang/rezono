"""Sweeping a cell in a pack with real cited origins must never blindly stamp `synthetic`
onto the swept cell or falsely satisfy / pollute `rezono:origins`
(decisions/fact-origin-required.md §§1-3, 5).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

pytest.importorskip("duckdb")
pytest.importorskip("rezono_compiler")

from rezono_publisher import batch, publish, store, sweep  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
PACK = "packs/p"
ROLES = {"checker": "complete", "viewer": "may_read"}
FACTS = "alpha:\n  - {id: a1, title: t, size: 1}\n  - {id: a2, title: u, size: 1}\n"
EXPLORE = {"value": {"step": 3}}
RULE = {
    "preconditions": {"slot_conditions": {"size": {"minimum_value": 6}}},
    "postconditions": {"slot_conditions": {"title": {"equals_string": "big"}}},
}
SWEEPS = {"sweeps": [{"name": "size_scale", "kind": "alpha", "key": "a1", "slot": "size"}]}
GREEN_VARIANTS = ["v-size_scale-00-3", "v-size_scale-01-3"]

VENDOR_DOCUMENT = {
    "kind": "document",
    "name": "vendor-catalog",
    "position": "pricing-table",
    "url": "https://vendor.example.org/catalog",
    "retrieved_at": "2026-01-01T00:00:00Z",
    "fragment_sha256": "a" * 64,
    "licence": "CC-BY-4.0",
    "attribution": "Example Vendor",
}


def _sh(*args: str, cwd: Path) -> str:
    return subprocess.run(args, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, message: str) -> None:
    (repo / "log.txt").write_text(message, encoding="utf-8")
    _sh("git", "add", ".", cwd=repo)
    _sh(
        "git",
        "-c", "user.name=Seed",
        "-c", "user.email=seed@example.invalid",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "-m", message,
        cwd=repo,
    )


def _make_repo(tmp_path: Path, sidecar: dict) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(ROOT / "compiler" / "tests" / "fixtures" / "minimal", repo / PACK)
    (repo / PACK / "facts").mkdir()
    (repo / PACK / "facts" / "a.yaml").write_text(FACTS, encoding="utf-8")
    (repo / PACK / "facts" / "a.sources.yaml").write_text(
        yaml.safe_dump(sidecar, sort_keys=False), encoding="utf-8"
    )
    schema_path = repo / PACK / "schema" / "minimal.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    schema["classes"]["Alpha"]["attributes"]["size"]["annotations"] = {"explore": EXPLORE}
    schema["classes"]["Alpha"]["rules"] = [RULE]
    schema_path.write_text(yaml.safe_dump(schema, sort_keys=False), encoding="utf-8")
    (repo / PACK / "sweeps.yaml").write_text(yaml.safe_dump(SWEEPS, sort_keys=False), encoding="utf-8")
    _sh("git", "init", "-q", "-b", "main", cwd=repo)
    _commit(repo, "seed")
    _commit(repo, "base")
    return repo


def _publish_main(repo: Path, st) -> tuple[str, dict]:
    base = _sh("git", "rev-parse", "HEAD", cwd=repo)
    epoch_num, knowledge_time = sweep.base_of(repo, base)
    ep = batch.epoch(repo / PACK, epoch=epoch_num, knowledge_time=knowledge_time, sources=[("rules", base)])
    manifest = publish.publish(ep, st, ROLES)
    return base, manifest


def _origins_check(manifest: dict) -> dict:
    found = [c for c in manifest.get("checks", []) if c.get("name") == "rezono:origins"]
    assert len(found) == 1, f"expected single rezono:origins check row, got {manifest.get('checks')}"
    return found[0]


def _checker_sources(st, manifest_id: str) -> list[dict]:
    key = publish.role_objects(st, "minimal", manifest_id, "checker")["sources.json"]
    return json.loads(st.get(key))


def test_sweep_preserves_real_origins_without_synthetic_stamp(tmp_path):
    repo = _make_repo(tmp_path, {"default": VENDOR_DOCUMENT})
    st = store.FileStore(tmp_path / "store")
    base, main_manifest = _publish_main(repo, st)

    assert _origins_check(main_manifest) == {"name": "rezono:origins", "status": "green", "violations": 0}
    main_sources = _checker_sources(st, main_manifest["id"])
    assert any(
        e["row"]["relation"] == "alpha__size"
        and json.loads(e["row"]["key"])[0] == "a1"
        and any(s["kind"] == "document" for s in e["sources"])
        for e in main_sources
    )

    done = sweep.run(repo, PACK, base, st, ROLES)
    assert [vid for vid, status in done if status == "manifest"] == GREEN_VARIANTS

    for vid in GREEN_VARIANTS:
        variant_manifest = json.loads(st.get(f"minimal/manifests/{vid}.json"))
        entries = _checker_sources(st, vid)
        swept_entries = [
            e for e in entries
            if e["row"]["relation"] == "alpha__size" and json.loads(e["row"]["key"])[0] == "a1"
        ]
        assert len(swept_entries) == 1, f"expected single swept alpha__size entry for a1 in {vid}: {swept_entries}"
        swept_kinds = {s["kind"] for s in swept_entries[0]["sources"]}
        assert "synthetic" not in swept_kinds, (
            f"swept cell in {vid} was blindly stamped synthetic: {swept_entries[0]}"
        )
        all_kinds = {s["kind"] for e in entries for s in e["sources"]}
        assert "synthetic" not in all_kinds, (
            f"variant {vid} polluted non-synthetic pack sources with synthetic: {entries}"
        )
        assert _origins_check(variant_manifest) == {
            "name": "rezono:origins",
            "status": "green",
            "violations": 0,
        }, f"sweeping a cited pack must not pollute rezono:origins: {variant_manifest['checks']}"


def test_sweep_does_not_falsely_satisfy_origins_check_with_synthetic(tmp_path):
    # a2 has a real document origin; a1 has only a self-citing git locator to its own fact file
    # (decisions/fact-origin-required.md §2: not an origin -> 3 uncited rows on main).
    sidecar = {
        "records": [
            {
                "of": {"kind": "alpha", "id": "a1"},
                "kind": "git",
                "name": "example/repo",
                "revision": "b" * 40,
                "position": "facts/a.yaml#L2",
            },
            {
                "of": {"kind": "alpha", "id": "a2"},
                **VENDOR_DOCUMENT,
            },
        ],
    }
    repo = _make_repo(tmp_path, sidecar)
    st = store.FileStore(tmp_path / "store")
    base, main_manifest = _publish_main(repo, st)

    assert _origins_check(main_manifest) == {"name": "rezono:origins", "status": "warning", "violations": 3}

    done = sweep.run(repo, PACK, base, st, ROLES)
    assert [vid for vid, status in done if status == "manifest"] == GREEN_VARIANTS

    for vid in GREEN_VARIANTS:
        variant_manifest = json.loads(st.get(f"minimal/manifests/{vid}.json"))
        entries = _checker_sources(st, vid)
        swept_entries = [
            e for e in entries
            if e["row"]["relation"] == "alpha__size" and json.loads(e["row"]["key"])[0] == "a1"
        ]
        assert len(swept_entries) == 1
        swept_kinds = {s["kind"] for s in swept_entries[0]["sources"]}
        assert "synthetic" not in swept_kinds, (
            f"sweeping uncited cell in {vid} must not stamp synthetic: {swept_entries[0]}"
        )
        assert _origins_check(variant_manifest) == {
            "name": "rezono:origins",
            "status": "warning",
            "violations": 3,
        }, (
            "sweeping an uncited cell must not reduce rezono:origins violations by stamping synthetic: "
            f"{variant_manifest['checks']}"
        )
