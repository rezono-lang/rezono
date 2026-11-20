"""The shared builds of examples/shared_builds.py are keyed on what a build reads: a pack that changed under the
same directory of shared builds is built again, never answered with the earlier build."""

import shutil

import pytest

pytest.importorskip("rezono_publisher")

import shared_builds  # noqa: E402

ARGUMENTS = {"epoch": 1, "knowledge_time": "2026-01-01T00:00:00Z", "sources": [("rules", "shared-builds")]}


def builds(directory):
    return sorted(p.name for p in directory.iterdir() if p.is_dir())


def test_a_changed_pack_under_the_same_directory_is_built_again(tmp_path, monkeypatch):
    root = tmp_path / "repository"
    pack = root / "examples" / "library"
    shutil.copytree(shared_builds.ROOT / "examples" / "library", pack)
    cache = tmp_path / "shared"
    cache.mkdir()
    monkeypatch.setattr(shared_builds, "ROOT", root)
    monkeypatch.setenv(shared_builds.SHARED, str(cache))

    first = shared_builds.epoch(pack, **ARGUMENTS)
    assert len(builds(cache)) == 1
    assert shared_builds.epoch(pack, **ARGUMENTS) == first  # unchanged: the same build, read again
    assert len(builds(cache)) == 1

    facts = pack / "facts" / "errors.yaml"
    facts.write_text(facts.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")
    second = shared_builds.epoch(pack, **ARGUMENTS)
    assert len(builds(cache)) == 2
    assert second.pack_sha256 != first.pack_sha256
