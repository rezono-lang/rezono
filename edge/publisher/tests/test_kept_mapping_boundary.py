"""Theory mapping files never activate an older archived publisher."""

import json
import shutil
from pathlib import Path

import pytest
import yaml

from rede_canon import sha256_hex
from rede_compiler import modules
from rede_publisher import batch, kept, publish, store

ROOT = Path(__file__).resolve().parents[3]


def pack_tree(root, where):
    main = root / "main"
    main.mkdir(parents=True)
    meta = {"name": "neutral", "version": "0.1.0", "default_language": "en"}
    if where == "import":
        other = root / "shared"
        other.mkdir()
        (other / "pack.yaml").write_text(yaml.safe_dump(meta | {"name": "shared"}), encoding="utf-8")
        (other / "views.yaml").write_text("not even parsed: [", encoding="utf-8")
        meta["imports"] = [{"name": "shared", "path": "../shared", "sha256": modules.pack_hash(other)}]
    elif where == "main":
        (main / "views.yaml").write_text("not even parsed: [", encoding="utf-8")
    elif where == "docs":
        (main / "docs").mkdir()
        (main / "docs/views.yaml").write_text("ordinary documentation", encoding="utf-8")
    (main / "pack.yaml").write_text(yaml.safe_dump(meta), encoding="utf-8")
    return main


@pytest.mark.parametrize("where", ["main", "import"])
def test_verified_pack_roots_refuse_mapping_presence_without_parsing(tmp_path, where):
    pack_tree(tmp_path, where)
    main, errors = kept.archived_pack(tmp_path)
    assert main is None
    assert len(errors) == 1 and "theory views.yaml execution is not supported" in errors[0]
    assert f"pack/{'shared' if where == 'import' else 'main'}/views.yaml" in errors[0]


@pytest.mark.parametrize("where", ["legacy", "docs"])
def test_legacy_pack_and_nested_document_are_not_theory_mapping_files(tmp_path, where):
    main = pack_tree(tmp_path, where)
    assert kept.archived_pack(tmp_path) == (main, [])


def test_bad_import_pin_is_refused_before_mapping_presence(tmp_path):
    pack_tree(tmp_path, "import")
    p = tmp_path / "shared/views.yaml"
    p.write_text("changed", encoding="utf-8")
    main, errors = kept.archived_pack(tmp_path)
    assert main is None and errors
    assert all("theory views.yaml execution" not in error for error in errors)


@pytest.mark.parametrize("where", ["main", "import", "legacy"])
def test_archive_preflight_runs_before_install_or_archived_code(tmp_path, monkeypatch, where):
    archived = tmp_path / "inputs"
    pack_tree(archived, where)
    events = []
    manifest = {"build": {"sha256": "a" * 64}}
    class Old:
        def get(self, key):
            return json.dumps(manifest).encode()
    def verify(pack_dir, old, key, tree):
        events.append("verified")
        shutil.copytree(archived, tree / "pack")
        return []
    class InstallReached(Exception):
        pass
    def install(*args, **kwargs):
        events.append("install")
        raise InstallReached
    monkeypatch.setattr(kept, "manifests", lambda _: ["neutral/manifests/m.json"])
    monkeypatch.setattr(kept, "verify", verify)
    monkeypatch.setattr(kept, "runtime", lambda: "not executed")
    monkeypatch.setattr(kept.subprocess, "run", install)
    monkeypatch.setattr(kept, "run_archived", lambda *a: pytest.fail("archived code executed"))
    if where == "legacy":
        with pytest.raises(InstallReached):
            kept.replay(archived, Old(), tmp_path / "new")
        assert events == ["verified", "install"]
    else:
        errors = kept.replay(archived, Old(), tmp_path / "new")
        assert any("views.yaml execution is not supported" in e for e in errors)
        assert events == ["verified"]


@pytest.mark.parametrize("where", ["main", "import"])
def test_real_archive_bytes_and_closure_refuse_before_replay(tmp_path, monkeypatch, where):
    main = pack_tree(tmp_path / "inputs", where)
    monkeypatch.setattr(batch, "libraries", lambda _: {})
    monkeypatch.setattr(batch.platform, "python_version", lambda: (ROOT / "requirements/.python-version").read_text().strip())
    record = batch.build_record()
    record["python"]["executable_sha256"] = sha256_hex(Path(kept.runtime()).resolve().read_bytes())
    body = publish.canonical(record)
    digest = sha256_hex(body)
    old = store.FileStore(kept.kept_dir(main))
    build = f"neutral/builds/{digest}.json"
    old.put_new(build, body)
    key = "neutral/manifests/m.json"
    old.put_new(key, publish.canonical({"id":"m", "compiler_sha256":record["compiler_sha256"],
        "pack_sha256":batch.tree_sha256(main), "build":{"uri":old.uri(build),"sha256":digest}}))
    data = kept.archive(ROOT, main)
    source = kept.source_dir(main)
    source.mkdir(parents=True)
    archive = source / f"{digest}.tar.gz"
    archive.write_bytes(data)
    kept.digest_path(archive).write_text(kept.digest_line(archive, data), encoding="utf-8")
    errors = kept.verify(main, old, key, tmp_path / "verified")
    assert any("theory views.yaml execution is not supported" in e for e in errors)
    monkeypatch.setattr(kept.subprocess, "run", lambda *a, **k: pytest.fail("installed archived code"))
    monkeypatch.setattr(kept, "run_archived", lambda *a: pytest.fail("ran archived code"))
    assert any("views.yaml execution is not supported" in e for e in kept.replay(main, old, tmp_path / "replay"))
