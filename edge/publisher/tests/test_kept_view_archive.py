"""View archive extension: real immutable checkpoints and hashes, without executing archived code."""

import gzip
import io
import json
from pathlib import Path
import shutil
import tarfile

import pytest
from rezono_canon import canonical_bytes, sha256_hex
from rezono_publisher import kept, kept_views, publish, view_build, views
from test_view_build import History, old_view


@pytest.fixture
def inputs(tmp_path, monkeypatch):
    root = view_build.ROOT
    pack = Path(shutil.copytree(root / "compiler/tests/fixtures/minimal", tmp_path / "pack"))
    monkeypatch.setattr(view_build, "executable", lambda _: "/trusted-node")
    monkeypatch.setattr(view_build, "runtime", lambda *a: {"executable_sha256": "a" * 64, "version": "v24.0.0",
                        "platform": "linux", "architecture": "x64", "versions": [{"name": "v8", "version": "13"}]})
    st = History()
    old_view(st, "m-1", "reader", b'{"revoked":"reader-old-private"}')
    old_view(st, "m-1", "other", b'{"private":"other-role-only"}')
    prepared = views.prepare(st, "p", "m-2", ["reader", "other"])
    record = {"format": kept.FORMAT, "views": prepared.component}
    body = publish.canonical(record)
    digest = sha256_hex(body)
    build = f"p/builds/{digest}.json"
    st.data[build] = body
    key = "p/manifests/m-2.json"
    st.data[key] = views.dumps({"id": "m-2", "build": {"uri": st.uri(build), "sha256": digest},
                              "snapshots": [{"role": r, "complete": False} for r in ("reader", "other")]})
    private = {}
    for capture in prepared.captures:
        checkpoint = views.checkpoint_key("p", "m-2", capture.role)
        private[checkpoint] = st.data.pop(checkpoint)
        st.data[views.index_key("p", "m-2", capture.role)] = views.dumps({
            "format": views.FORMAT, "pack": "p", "manifest": "m-2", "role": capture.role, "relayout": False,
            "capture_sha256": capture.sha256, "previous": capture.descriptor()["previous"]})
    return root, pack, st, key, private, prepared


def members(data):
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers()}


def repack(files, extra=None):
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w") as tar:
        for path, body in sorted(files.items()):
            entry = tarfile.TarInfo(path)
            entry.size = len(body)
            tar.addfile(entry, io.BytesIO(body))
        if extra:
            tar.addfile(extra)
    return out.getvalue()


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
def test_private_extension_roundtrip_is_exact_deterministic_and_does_not_publish(inputs, monkeypatch):
    root, pack, st, key, private, prepared = inputs
    before = dict(st.data)
    monkeypatch.setattr(kept.subprocess, "run", lambda *a, **k: pytest.fail("archive primitive executed code"))
    archive = kept_views.archive(root, pack, st, key, private)
    assert kept_views.archive(root, pack, st, key, private) == archive
    verified = kept_views.verify(archive, st, key)
    assert dict(verified.checkpoints) == private
    assert {p: sha256_hex(b) for p, b in verified.sources} == {e["path"]: e["sha256"] for e in prepared.component["files"]}
    assert len(archive) > 0 and sum(len(b) for _, b in verified.sources) > 0
    assert sum(len(b) for _, b in verified.checkpoints) == sum(map(len, private.values()))
    assert st.data == before and not any("/private/view-inputs/" in p for p in st.data)
    for capture in prepared.captures:
        restored = view_build.restore(private[views.checkpoint_key("p", "m-2", capture.role)],
                                      prepared.component, "p", "m-2", capture.role, False)
        assert restored == capture
    # Only the optional extension is verified: replay is still explicitly unsupported until wiring exists.
    assert any("view-aware" in e for e in kept.verify(pack, st, key, pack.parent / "unpacked"))


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
@pytest.mark.parametrize("damage", ["source", "missing-source", "extra-source", "missing-capture", "extra-role",
                                    "role", "mode", "payload", "checkpoint-build"])
def test_adversarial_extension_is_refused_before_execution(inputs, monkeypatch, damage):
    root, pack, st, key, private, _ = inputs
    archive = kept_views.archive(root, pack, st, key, private)
    files = members(archive)
    checkpoint = kept_views.input_member("p", "m-2", "reader")
    if damage == "source":
        files["viewer/scripts/views.ts"] += b"\n// changed\n"
    elif damage == "missing-source":
        del files["viewer/package-lock.json"]
    elif damage == "extra-source":
        files["viewer/src/lib/unrecorded.ts"] = b"not in the recorded inventory"
    elif damage == "missing-capture":
        del files[checkpoint]
    elif damage == "extra-role":
        files[checkpoint.replace("reader.json", "foreign.json")] = files[checkpoint]
    else:
        doc = json.loads(files[checkpoint])
        if damage == "role":
            doc["capture"]["role"] = "other"
        elif damage == "mode":
            doc["capture"]["relayout"] = True
        elif damage == "payload":
            doc["layouts"][0]["bytes"] = "Zm9yZ2Vk"
        else:
            doc["build"]["node"]["executable_sha256"] = "f" * 64
        files[checkpoint] = canonical_bytes(doc)
    monkeypatch.setattr(kept.subprocess, "run", lambda *a, **k: pytest.fail("unverified archive executed code"))
    with pytest.raises(kept_views.ArchiveError):
        kept_views.verify(repack(files), st, key)


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
@pytest.mark.parametrize("damage", ["commitment", "previous", "role", "missing"])
def test_capture_is_bound_to_the_kept_target_role_index_not_its_own_assertion(inputs, damage):
    root, pack, st, key, private, _ = inputs
    archive = kept_views.archive(root, pack, st, key, private)
    index_key = views.index_key("p", "m-2", "reader")
    d = json.loads(st.data[index_key])
    if damage == "commitment":
        d["capture_sha256"] = "f" * 64
    elif damage == "previous":
        d["previous"]["manifest"] = "m-0"
    elif damage == "role":
        d["role"] = "other"
    if damage == "missing":
        del st.data[index_key]
    else:
        st.data[index_key] = views.dumps(d)
    with pytest.raises(kept_views.ArchiveError):
        kept_views.verify(archive, st, key)


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
@pytest.mark.parametrize("name,kind", [("../outside", "file"), ("viewer/src/lib/link.ts", "symlink"),
                                       ("viewer/scripts/views.ts", "duplicate"), ("bin/node", "file")])
def test_unsafe_or_undeclared_archive_members_are_refused(inputs, name, kind):
    root, pack, st, key, private, _ = inputs
    files = members(kept_views.archive(root, pack, st, key, private))
    entry = tarfile.TarInfo(name)
    if kind == "symlink":
        entry.type, entry.linkname = tarfile.SYMTYPE, "../../outside"
    with pytest.raises(kept_views.ArchiveError):
        kept_views.verify(repack(files, entry), st, key)


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
def test_creator_requires_explicit_complete_private_inputs(inputs):
    root, pack, st, key, private, _ = inputs
    # Even a store adapter containing production checkpoints is never enumerated for archival.
    st.data.update(private)
    with pytest.raises(kept_views.ArchiveError, match="explicit checkpoint set"):
        kept_views.archive(root, pack, st, key, {})


def edit_trusted_inventory(files, st, key, keep):
    """Also alter the expected kept build/manifest, beyond merely attacking the source archive."""
    m = json.loads(st.data[key])
    record = json.loads(st.data[views.key_of(m["build"]["uri"])])
    for e in record["views"]["files"]:
        if e["path"] not in keep:
            del files[e["path"]]
    record["views"]["files"] = [e for e in record["views"]["files"] if e["path"] in keep]
    for path in files:
        if path.startswith(kept_views.PRIVATE):
            d = json.loads(files[path])
            d["build"] = record["views"]
            files[path] = canonical_bytes(d)
    body = publish.canonical(record)
    digest = sha256_hex(body)
    build = f"p/builds/{digest}.json"
    st.data[build] = body
    m["build"] = {"uri": st.uri(build), "sha256": digest}
    st.data[key] = views.dumps(m)


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
def test_a_self_consistent_core_only_inventory_is_refused(inputs):
    root, pack, st, key, private, _ = inputs
    files = members(kept_views.archive(root, pack, st, key, private))
    keep = {"viewer/scripts/views.ts", "viewer/package.json", "viewer/package-lock.json"}
    edit_trusted_inventory(files, st, key, keep)
    with pytest.raises(kept_views.ArchiveError, match="critical source roots"):
        kept_views.verify(repack(files), st, key)


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
def test_extension_checks_pinned_bytes_but_does_not_claim_independent_dependency_closure(inputs):
    root, pack, st, key, private, prepared = inputs
    files = members(kept_views.archive(root, pack, st, key, private))
    removed = "viewer/src/lib/layout/names.ts"
    keep = {e["path"] for e in prepared.component["files"]} - {removed}
    assert removed in files
    edit_trusted_inventory(files, st, key, keep)
    # This explicitly changes the trusted kept build too. The extension can only verify its declared list;
    # it cannot infer a missing transitive dependency from that altered assertion. Replay stays blocked.
    checked = kept_views.verify(repack(files), st, key)
    assert removed not in dict(checked.sources)
    rebound = {views.checkpoint_key("p", "m-2", role): files[kept_views.input_member("p", "m-2", role)]
               for role in ("reader", "other")}
    with pytest.raises(kept_views.ArchiveError, match="current source inventory differs"):
        kept_views.archive(root, pack, st, key, rebound)
    assert any("view-aware" in e for e in kept.verify(pack, st, key, pack.parent / "still-not-replayable"))


@pytest.mark.xfail(strict=True, reason="viewer/src/lib is not in the standalone repository")
@pytest.mark.parametrize("damage", ["raw-json", "raw-tar", "oversized-member", "too-many-members"])
def test_malformed_or_oversized_input_is_refused_without_a_decode_fallback(inputs, monkeypatch, damage):
    root, pack, st, key, private, _ = inputs
    data = kept_views.archive(root, pack, st, key, private)
    if damage == "raw-json":
        files = members(data)
        files[kept_views.input_member("p", "m-2", "reader")] = b"{broken"
        data = repack(files)
    elif damage == "raw-tar":
        data = b"not an archive"
    elif damage == "oversized-member":
        entry = tarfile.TarInfo("viewer/scripts/views.ts")
        entry.size = kept_views.MAX_MEMBER_BYTES + 1
        # Header only: the bound must be checked before attempting a huge read/allocation.
        data = gzip.compress(entry.tobuf() + b"\0" * 1024)
    else:
        monkeypatch.setattr(kept_views, "MAX_MEMBERS", 1)
    monkeypatch.setattr(kept.subprocess, "run", lambda *a, **k: pytest.fail("bad archive executed code"))
    with pytest.raises(kept_views.ArchiveError):
        kept_views.verify(data, st, key)


def physical_metadata(kind, payload, count=1):
    """Synthetic physical headers keep metadata tests tiny, with no large payload allocation."""
    entry = tarfile.TarInfo("ExtendedHeader")
    entry.type, entry.size = kind, len(payload)
    block = entry.tobuf(format=tarfile.GNU_FORMAT) + payload
    block += b"\0" * (-len(payload) % tarfile.BLOCKSIZE)
    regular = tarfile.TarInfo("viewer/scripts/views.ts").tobuf()
    return gzip.compress(block * count + regular + b"\0" * 1024)


@pytest.mark.parametrize("kind", [tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK])
def test_gnu_extended_metadata_is_bounded_before_the_tar_parser(monkeypatch, kind):
    data = physical_metadata(kind, b"x" * 8192 + b"\0")
    monkeypatch.setattr(kept_views, "MAX_MEMBER_BYTES", 128)
    monkeypatch.setattr(kept_views, "MAX_ARCHIVE_BYTES", 20000)
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("GNU parser ran before physical bounds"))
    with pytest.raises(kept_views.ArchiveError, match="metadata exceed"):
        kept_views._members(data)


def test_pax_comment_counts_toward_the_expanded_stream_bound_before_parsing(monkeypatch):
    out = io.BytesIO()
    with tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as tar:
        entry = tarfile.TarInfo("viewer/scripts/views.ts")
        entry.pax_headers = {"comment": "x" * 8192}
        tar.addfile(entry, io.BytesIO(b""))
    data = gzip.compress(out.getvalue())
    assert len(data) < 2048 < len(out.getvalue())
    monkeypatch.setattr(kept_views, "MAX_MEMBER_BYTES", 128)
    monkeypatch.setattr(kept_views, "MAX_ARCHIVE_BYTES", 2048)
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("PAX parser ran before expanded-stream bound"))
    with pytest.raises(kept_views.ArchiveError, match="expanded tar stream"):
        kept_views._members(data)


@pytest.mark.parametrize("count,member_limit", [(3, 2), (17, 50000)])
def test_many_hidden_metadata_headers_are_bounded_before_tarfile_recursion(monkeypatch, count, member_limit):
    data = physical_metadata(tarfile.XGLTYPE, b"13 comment=x\n", count)
    monkeypatch.setattr(kept_views, "MAX_MEMBERS", member_limit)
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("metadata parser ran before count/chain bound"))
    with pytest.raises(kept_views.ArchiveError, match="verification bounds"):
        kept_views._members(data)


def test_a_legitimate_long_pax_source_path_still_decodes():
    path = "viewer/src/lib/" + "long-name-" * 14 + ".ts"
    data = repack({path: b"valid source"})
    assert kept_views._members(data) == {path: b"valid source"}


def pax_record(key, value):
    content = key.encode() + b"=" + value.encode() + b"\n"
    size = len(content) + 2
    while len(str(size)) + 1 + len(content) != size:
        size = len(str(size)) + 1 + len(content)
    return str(size).encode() + b" " + content


def physical_member(name, kind, body=b""):
    entry = tarfile.TarInfo(name)
    entry.type, entry.size = kind, len(body)
    return entry.tobuf(format=tarfile.GNU_FORMAT) + body + b"\0" * (-len(body) % tarfile.BLOCKSIZE)


def test_pax_size_zero_cannot_hide_a_metadata_chain_from_the_physical_pass(monkeypatch):
    # Exact review repro: tarfile used to apply size=0 to the carrier, then discover 17 headers
    # inside what the physical precheck skipped as ordinary payload (20 headers with a cap of 3).
    hidden = physical_member("meta", tarfile.XGLTYPE, pax_record("comment", "x")) * 17
    hidden += physical_member("viewer/src/lib/last.ts", tarfile.REGTYPE)
    raw = physical_member("local", tarfile.XHDTYPE, pax_record("size", "0"))
    raw += physical_member("viewer/scripts/views.ts", tarfile.REGTYPE, hidden) + b"\0" * 1024
    monkeypatch.setattr(kept_views, "MAX_MEMBERS", 3)
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("effective-size parser ran before refusal"))
    with pytest.raises(kept_views.ArchiveError, match="unsupported PAX field"):
        kept_views._members(gzip.compress(raw))


@pytest.mark.parametrize("kind", [tarfile.XHDTYPE, tarfile.XGLTYPE])
@pytest.mark.parametrize("key,value", [
    ("size", "0"), ("size", "4096"), ("GNU.sparse.map", "0,1"), ("GNU.sparse.size", "4096"),
    ("GNU.sparse.major", "1"), ("GNU.sparse.realsize", "4096"), ("SCHILY.realsize", "4096"),
])
def test_local_and_global_size_sparse_and_unknown_dialects_are_refused_before_parsing(monkeypatch, kind, key, value):
    raw = physical_member("metadata", kind, pax_record(key, value))
    raw += physical_member("viewer/scripts/views.ts", tarfile.REGTYPE) + b"\0" * 1024
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("unsupported PAX dialect reached parser"))
    with pytest.raises(kept_views.ArchiveError, match="unsupported PAX field"):
        kept_views._members(gzip.compress(raw))


@pytest.mark.parametrize("kind", [tarfile.GNUTYPE_SPARSE, tarfile.SOLARIS_XHDTYPE])
def test_sparse_and_other_physical_metadata_dialects_are_refused_before_parsing(monkeypatch, kind):
    raw = physical_member("viewer/scripts/views.ts", kind) + b"\0" * 1024
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("unsupported physical dialect reached parser"))
    with pytest.raises(kept_views.ArchiveError, match="unsupported physical member type"):
        kept_views._members(gzip.compress(raw))


@pytest.mark.parametrize("payload", [b"0 comment=x\n", b"99 comment=x\n", b"12 comment=x", b"not framed\n"])
def test_pax_framing_must_be_checked_before_the_general_parser(monkeypatch, payload):
    raw = physical_member("metadata", tarfile.XHDTYPE, payload)
    raw += physical_member("viewer/scripts/views.ts", tarfile.REGTYPE) + b"\0" * 1024
    monkeypatch.setattr(kept_views.tarfile, "open", lambda *a, **k: pytest.fail("malformed metadata reached parser"))
    with pytest.raises(kept_views.ArchiveError, match="malformed PAX record"):
        kept_views._members(gzip.compress(raw))


def test_ordinary_global_git_comment_and_local_long_path_metadata_still_decode():
    path = "viewer/src/lib/" + "long-name-" * 14 + ".ts"
    # Descriptive values may contain text resembling a forbidden field; only record keys decide.
    raw = physical_member("global", tarfile.XGLTYPE, pax_record("comment", "commit=abc; size=0\nGNU.sparse.size=2"))
    raw += physical_member("local", tarfile.XHDTYPE, pax_record("path", path) + pax_record("mtime", "0.25"))
    raw += physical_member("short.ts", tarfile.REGTYPE, b"source bytes") + b"\0" * 1024
    assert kept_views._members(gzip.compress(raw)) == {path: b"source bytes"}
