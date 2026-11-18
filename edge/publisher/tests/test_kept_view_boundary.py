"""Until C3 step 2, a view-aware record cannot be mistaken for a replayable kept publication."""

import io
from pathlib import Path
import shutil
import tarfile
from types import SimpleNamespace

import pytest
from rezono_canon import sha256_hex
from rezono_publisher import batch, kept, publish, store, view_build


def archive_fixture(tmp_path, monkeypatch, with_views):
    root = view_build.ROOT
    pack = Path(shutil.copytree(root / "compiler/tests/fixtures/minimal", tmp_path / "pack"))
    # Isolate the archive capability from the unrelated host runtime/library installation.
    monkeypatch.setattr(batch, "libraries", lambda _: {})
    monkeypatch.setattr(batch.platform, "python_version", lambda: (root / "requirements/.python-version").read_text().strip())
    record = batch.build_record()
    record["python"]["executable_sha256"] = sha256_hex(Path(kept.runtime()).resolve().read_bytes())
    if with_views:
        record["views"] = {"format": view_build.FORMAT, "files": view_build.inventory(), "node": {
            "version": "v24.0.0", "platform": "linux", "architecture": "x64", "executable_sha256": "b" * 64,
            "versions": [{"name": "v8", "version": "13.6.233"}]}}
    body = publish.canonical(record)
    digest = sha256_hex(body)
    st = store.FileStore(kept.kept_dir(pack))
    build = f"minimal/builds/{digest}.json"
    st.put_new(build, body)
    manifest_key = "minimal/manifests/m-1.json"
    m = {"id": "m-1", "compiler_sha256": record["compiler_sha256"], "pack_sha256": batch.tree_sha256(pack),
         "build": {"uri": st.uri(build), "sha256": digest}}
    st.put_new(manifest_key, publish.canonical(m))
    data = kept.archive(root, pack)
    directory = kept.source_dir(pack)
    directory.mkdir(parents=True)
    path = directory / f"{digest}.tar.gz"
    path.write_bytes(data)
    kept.digest_path(path).write_text(kept.digest_line(path, data), encoding="utf-8")
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        assert not any(n.startswith("viewer/") or "/private/view-inputs/" in n for n in tar.getnames())
    return pack, st, manifest_key


@pytest.mark.parametrize(
    "with_views",
    [False, pytest.param(True, marks=pytest.mark.xfail(strict=True, reason="later: tekenweergaven"))],
)
def test_verify_preserves_viewless_support_but_refuses_an_incomplete_view_archive(tmp_path, monkeypatch, with_views):
    pack, st, key = archive_fixture(tmp_path, monkeypatch, with_views)
    output = tmp_path / "unpacked"
    refused = kept.verify(pack, st, key, output)
    if with_views:
        # Before the guard, this exact source-only archive returned [] despite naming missing view inputs.
        assert any("view-aware" in e and "C3 step 2" in e for e in refused)
        assert not output.exists(), "nothing from an unsupported archive is unpacked or run"
    else:
        assert refused == [] and (output / "compiler/rezono_compiler").is_dir()


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_replay_refuses_view_aware_capability_before_any_archived_subprocess(tmp_path, monkeypatch):
    pack, st, _ = archive_fixture(tmp_path, monkeypatch, True)
    monkeypatch.setattr(kept.subprocess, "run", lambda *a, **k: pytest.fail("unsupported archived code executed"))
    refused = kept.replay(pack, st, tmp_path / "new")
    assert any("view-aware" in e for e in refused)
    assert not (tmp_path / "new/store").exists()


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_current_replay_cannot_silently_drop_the_view_component(tmp_path, monkeypatch):
    pack, st, _ = archive_fixture(tmp_path, monkeypatch, True)
    monkeypatch.setattr(batch, "epoch", lambda *a, **k: pytest.fail("view-aware current replay computed an epoch"))
    assert any("view-aware" in e for e in kept.check(pack, current=True))
    with pytest.raises(ValueError, match="view-aware"):
        kept.remake(pack, st, store.FileStore(tmp_path / "direct"))
    assert not (tmp_path / "direct").exists()


def test_make_refuses_a_view_aware_epoch_before_publication(tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "epoch", lambda *a, **k: SimpleNamespace(build={"views": {"format": view_build.FORMAT}}))
    monkeypatch.setattr(publish, "publish", lambda *a, **k: pytest.fail("incomplete view-aware kept publication written"))
    with pytest.raises(ValueError, match="view-aware.*C3 step 2"):
        kept.make(tmp_path, {"viewer": "may_read"})
    assert not kept.kept_dir(tmp_path).exists() and not kept.source_dir(tmp_path).exists()
