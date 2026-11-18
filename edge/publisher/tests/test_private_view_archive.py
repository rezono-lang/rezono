"""Synthetic private candidates; full existing base/extension checks, no engine or provisioning."""

import copy
import json
import os
from pathlib import Path
import subprocess

import pytest

from rezono_canon import canonical_sha256, sha256_hex
from rezono_publisher import batch, kept, kept_views, private_view_archive as candidates, publish
from test_kept_view_archive import inputs as view_inputs  # noqa: F401 (a pytest fixture)


@pytest.fixture
def inputs(view_inputs, tmp_path, monkeypatch):
    root, pack, old, key, private, prepared = view_inputs
    monkeypatch.setattr(batch, "libraries", lambda _: {})
    monkeypatch.setattr(batch.platform, "python_version", lambda: (root / "requirements/.python-version").read_text().strip())
    record = batch.build_record() | {"views": prepared.component}
    record["python"]["executable_sha256"] = sha256_hex(Path(kept.runtime()).resolve().read_bytes())
    body = publish.canonical(record)
    digest = sha256_hex(body)
    build = f"p/builds/{digest}.json"
    old.data[build] = body
    manifest = json.loads(old.get(key)) | {"build": {"uri": old.uri(build), "sha256": digest},
        "compiler_sha256": record["compiler_sha256"], "pack_sha256": batch.tree_sha256(pack)}
    old.data[key] = publish.canonical(manifest)
    destination = tmp_path / "private"
    destination.mkdir()
    return dict(root=root, pack_dir=pack, target=old.data.copy(), manifest_key=key,
                checkpoints=private.copy(), destination=destination)


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_receipt_binds_exact_manifest_capture_commitments_and_payloads(inputs):
    before = copy.deepcopy(inputs)
    result = candidates.commit_archive(**inputs)
    receipt_bytes = (result.directory / "receipt.json").read_bytes()
    receipt = json.loads(receipt_bytes)
    assert result.directory.name == result.sha256 == sha256_hex(receipt_bytes)
    assert receipt["manifest_sha256"] == sha256_hex(inputs["target"][inputs["manifest_key"]])
    assert receipt["manifest_key"] == inputs["manifest_key"]
    for key, checkpoint in inputs["checkpoints"].items():
        assert receipt["captures"][key] == {"checkpoint_sha256": sha256_hex(checkpoint),
            "capture_sha256": canonical_sha256(json.loads(checkpoint)["capture"])}
    for name, spec in receipt["files"].items():
        data = (result.directory / name).read_bytes()
        assert spec == {"sha256": sha256_hex(data), "size": str(len(data))}
    assert inputs == before and len(list(result.directory.iterdir())) == 3
    times = {p.name: p.stat().st_mtime_ns for p in result.directory.iterdir()}
    assert candidates.commit_archive(**inputs) == result
    assert times == {p.name: p.stat().st_mtime_ns for p in result.directory.iterdir()}
    assert any("view-aware" in e for e in kept.verify(inputs["pack_dir"], inputs["target"], inputs["manifest_key"], result.directory / "no-replay"))


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
@pytest.mark.parametrize("after", [1, 2])
def test_interrupted_pair_is_not_committed_and_same_retry_completes(inputs, monkeypatch, after):
    real, calls = candidates._put_new, []
    def interrupted(path, body):
        real(path, body)
        calls.append(path)
        if len(calls) == after:
            raise OSError("synthetic interruption")
    monkeypatch.setattr(candidates, "_put_new", interrupted)
    with pytest.raises(OSError, match="synthetic interruption"):
        candidates.commit_archive(**inputs)
    (partial,) = inputs["destination"].iterdir()
    assert not (partial / "receipt.json").exists()
    assert len(list(partial.iterdir())) == after
    monkeypatch.setattr(candidates, "_put_new", real)
    assert candidates.commit_archive(**inputs).directory == partial
    assert len(list(partial.iterdir())) == 3


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
@pytest.mark.parametrize("part", ["tar.gz", "sha256", "receipt.json"])
def test_existing_mismatch_is_never_overwritten(inputs, part):
    result = candidates.commit_archive(**inputs)
    path = next(p for p in result.directory.iterdir() if p.name.endswith(part))
    path.write_bytes(b"conflict")
    before = {p.name: p.read_bytes() for p in result.directory.iterdir()}
    with pytest.raises(ValueError, match="conflicting bytes"):
        candidates.commit_archive(**inputs)
    assert before == {p.name: p.read_bytes() for p in result.directory.iterdir()}


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_committed_missing_payload_is_corruption_not_an_implicit_repair(inputs):
    result = candidates.commit_archive(**inputs)
    next(result.directory.glob("*.tar.gz")).unlink()
    with pytest.raises(ValueError, match="committed private candidate is incomplete"):
        candidates.commit_archive(**inputs)
    assert not list(result.directory.glob("*.tar.gz"))


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
@pytest.mark.parametrize("damage", ["role", "base"])
def test_both_existing_verifications_finish_before_any_candidate_output(inputs, damage):
    if damage == "role":
        key = next(iter(inputs["checkpoints"]))
        checkpoint = json.loads(inputs["checkpoints"][key])
        checkpoint["capture"]["role"] = "wrong"
        inputs["checkpoints"][key] = publish.canonical(checkpoint)
    else:
        manifest = json.loads(inputs["target"][inputs["manifest_key"]])
        record = json.loads(inputs["target"][kept.key(manifest["build"]["uri"])])
        record["publisher"] = "0" * 64
        body = publish.canonical(record)
        digest = sha256_hex(body)
        key = f"p/builds/{digest}.json"
        inputs["target"][key] = body
        manifest["build"] = {"uri": f"s3://rezono/{key}", "sha256": digest}
        inputs["target"][inputs["manifest_key"]] = publish.canonical(manifest)
    with pytest.raises(kept_views.ArchiveError):
        candidates.commit_archive(**inputs)
    assert list(inputs["destination"].iterdir()) == []


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_inputs_are_copied_once_instead_of_reading_a_live_provider(inputs, monkeypatch):
    real = kept_views.archive
    def change_original(root, pack, target, key, checkpoints):
        inputs["target"].clear()
        inputs["checkpoints"].clear()
        return real(root, pack, target, key, checkpoints)
    monkeypatch.setattr(kept_views, "archive", change_original)
    assert (candidates.commit_archive(**inputs).directory / "receipt.json").exists()


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_same_build_and_archive_for_two_epochs_have_distinct_candidate_identity(inputs):
    manifest = json.loads(inputs["target"][inputs["manifest_key"]])
    manifest["snapshots"] = []
    inputs["target"][inputs["manifest_key"]] = publish.canonical(manifest)
    inputs["checkpoints"] = {}
    first = candidates.commit_archive(**inputs)
    manifest["id"] = "m-3"
    inputs["manifest_key"] = "p/manifests/m-3.json"
    inputs["target"][inputs["manifest_key"]] = publish.canonical(manifest)
    second = candidates.commit_archive(**inputs)
    a, b = (json.loads((r.directory / "receipt.json").read_bytes()) for r in (first, second))
    assert a["build_sha256"] == b["build_sha256"] and a["files"] == b["files"]
    assert first.directory != second.directory and a["manifest_sha256"] != b["manifest_sha256"]


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
@pytest.mark.parametrize("location", ["checkout", "published", "relative"])
def test_obvious_public_or_implicit_destinations_fail_closed(inputs, location):
    if location == "checkout":
        inputs["destination"] = inputs["pack_dir"]
    elif location == "published":
        inputs["destination"] = inputs["destination"] / "published"
        inputs["destination"].mkdir()
    else:
        inputs["destination"] = Path("implicit")
    with pytest.raises(ValueError, match="destination"):
        candidates.commit_archive(**inputs)


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_linked_destination_is_refused_without_touching_target(inputs):
    link = inputs["destination"].parent / "linked"
    try:
        link.symlink_to(inputs["destination"], target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        subprocess.run(["cmd.exe", "/c", "mklink", "/J", str(link), str(inputs["destination"])],
                       check=True, capture_output=True)
    inputs["destination"] = link
    with pytest.raises(ValueError, match="path is linked"):
        candidates.commit_archive(**inputs)
    assert list(link.iterdir()) == []


@pytest.mark.parametrize("limit,reason", [("MAX_MEMBERS", "input count"), ("MAX_ARCHIVE_BYTES", "input bytes")])
def test_input_bounds_precede_hashing_or_archive_construction(monkeypatch, limit, reason):
    monkeypatch.setattr(kept_views, limit, 1)
    monkeypatch.setattr(kept_views, "archive", lambda *a: pytest.fail("oversized inventory was archived"))
    with pytest.raises(ValueError, match=reason):
        candidates.commit_archive(Path("."), Path("."), {"a": b"a", "b": b"b"}, "a", {}, Path("."))


def test_live_store_protocol_is_not_an_input_inventory():
    class Live:
        def get(self, key):
            pytest.fail("live provider was read")
    with pytest.raises(ValueError, match="explicit byte dictionaries"):
        candidates.commit_archive(Path("."), Path("."), Live(), "unused", {}, Path("."))


def test_archive_bound_precedes_digest_hashing(tmp_path, monkeypatch):
    monkeypatch.setattr(kept_views, "MAX_ARCHIVE_BYTES", 1)
    monkeypatch.setattr(kept_views, "archive", lambda *a: b"xx")
    monkeypatch.setattr(kept, "digest_line", lambda *a: pytest.fail("oversized archive was hashed"))
    with pytest.raises(ValueError, match="archive exceeds"):
        candidates.commit_archive(Path.cwd(), Path.cwd(), {}, "unused", {}, tmp_path)


@pytest.mark.parametrize("component", ["published.", "published ", "expected.", "expected "])
@pytest.mark.parametrize("intermediate", [False, True])
def test_dot_space_aliases_are_refused_before_archive_or_output(tmp_path, monkeypatch, component, intermediate):
    parent = tmp_path / component
    actual_parent = tmp_path / component.rstrip(". ") if os.name == "nt" else parent
    actual_parent.mkdir()
    destination = parent / "safe" if intermediate else parent
    actual = actual_parent / "safe" if intermediate else actual_parent
    actual.mkdir(exist_ok=True)
    if os.name == "nt":
        assert component.rstrip(". ") in destination.resolve().parts, "exercise a real Windows alias"
    monkeypatch.setattr(kept_views, "archive", lambda *a: pytest.fail("aliased destination reached archive creation"))
    with pytest.raises(ValueError, match="destination"):
        candidates.commit_archive(Path.cwd(), Path.cwd(), {}, "unused", {}, destination)
    assert list(actual.iterdir()) == []


def test_resolved_public_marker_cannot_be_hidden_by_original_alias(tmp_path, monkeypatch):
    alias, public = tmp_path / "alias", tmp_path / "published"
    alias.mkdir()
    public.mkdir()
    real = Path.resolve
    monkeypatch.setattr(Path, "resolve", lambda p, *a, **k: public if p == alias else real(p, *a, **k))
    monkeypatch.setattr(kept_views, "archive", lambda *a: pytest.fail("resolved public path reached archive creation"))
    with pytest.raises(ValueError, match="destination"):
        candidates.commit_archive(Path.cwd(), Path.cwd(), {}, "unused", {}, alias)
    assert list(alias.iterdir()) == list(public.iterdir()) == []


def test_safe_absolute_anchor_is_not_a_nonportable_component(tmp_path):
    assert candidates._destination(Path.cwd(), Path.cwd(), tmp_path) == tmp_path.resolve()
