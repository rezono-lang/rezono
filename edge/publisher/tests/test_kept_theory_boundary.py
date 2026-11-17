"""Current metadata guards verified archives before any install or archived-code execution."""

import json

import pytest
import yaml

from rezono_publisher import kept


class ReachedInstall(Exception):
    pass


def replay_fixture(tmp_path, monkeypatch, metadata):
    main = tmp_path / "verified-pack"
    main.mkdir()
    (main / "pack.yaml").write_text(metadata, encoding="utf-8")
    keys = ["neutral/manifests/m-1.json", "neutral/manifests/m-2.json"]
    events = []

    class OldStore:
        def get(self, key):
            assert key in keys
            return json.dumps({"build": {"sha256": ("1" if key == keys[0] else "2") * 64}}).encode()

    def verify(pack_dir, old, key, tree):
        events.append(("verify", key))
        return []

    def archived_pack(path):
        assert path.name == "pack"
        assert [e[0] for e in events[:2]] == ["verify", "verify"]
        events.append(("metadata", str(path)))
        return main, []

    def install(*args, **kwargs):
        events.append(("install", ""))
        raise ReachedInstall

    def forbidden(*args, **kwargs):
        pytest.fail("the archive was executed during metadata preflight")

    monkeypatch.setattr(kept, "manifests", lambda _: keys)
    monkeypatch.setattr(kept, "verify", verify)
    monkeypatch.setattr(kept, "archived_pack", archived_pack)
    monkeypatch.setattr(kept.subprocess, "run", install)
    monkeypatch.setattr(kept, "run_archived", forbidden)
    # No runtime lookup, subprocess or installation is necessary to observe this boundary.
    monkeypatch.setattr(kept, "runtime", lambda: "sentinel-python")
    return lambda: kept.replay(main, OldStore(), tmp_path / "replay"), events


BASE = {"name": "neutral", "version": "0.1.0", "default_language": "en"}


def test_declared_theory_archive_is_refused_before_any_install(tmp_path, monkeypatch):
    replay, events = replay_fixture(tmp_path, monkeypatch, yaml.safe_dump(BASE | {"theory": True}))
    assert any("theory pack cannot publish" in line for line in replay())
    assert not any(event == "install" for event, _ in events)


@pytest.mark.parametrize("metadata", ["not: [valid", "[]", yaml.safe_dump(BASE | {"theory": "false"}),
                                      yaml.safe_dump(BASE | {"theory": None}), yaml.safe_dump(BASE | {"theory": 0})])
def test_malformed_archive_metadata_fails_closed_before_install(tmp_path, monkeypatch, metadata):
    replay, events = replay_fixture(tmp_path, monkeypatch, metadata)
    assert replay()
    assert not any(event == "install" for event, _ in events)


@pytest.mark.parametrize("metadata", [BASE, BASE | {"theory": False},
                                      BASE | {"imports": [{"name": "neutral-theory", "path": "../theory", "sha256": "a" * 64}]}])
def test_legacy_or_domain_metadata_reaches_existing_install_boundary(tmp_path, monkeypatch, metadata):
    replay, events = replay_fixture(tmp_path, monkeypatch, yaml.safe_dump(metadata))
    with pytest.raises(ReachedInstall):
        replay()
    assert [e for e, _ in events].count("metadata") == 2
    assert [e for e, _ in events].count("install") == 1
