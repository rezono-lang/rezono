"""C3 replay of a kept view publication from its private candidate (B25), offline.

Every refusal must come before anything is installed or run: the installers and the archived run fail the test
if reached. The valid case fakes only the three steps that need the pinned Linux runtime and the network (the
archived Python install, `npm ci` of the archived lock, and the archived publisher's run) and checks what the
driver hands them: the verified base and view sources laid out at their paths, the frozen role checkpoints in
the new store, `--views` and the verified Node. The byte-for-byte comparison then runs as in `check`.
"""

import gzip
import io
import json
import os
from pathlib import Path
import tarfile
from urllib.parse import unquote

import pytest

from rezono_canon import canonical_bytes, canonical_sha256, sha256_hex
from rezono_publisher import batch, kept, kept_views, private_view_archive as candidates, publish, store, views
from test_kept_view_archive import inputs as view_inputs  # noqa: F401  (fixture of the fixture below)
from test_private_view_archive import inputs  # noqa: F401  (fixture)


def never(*a, **k):
    pytest.fail("installed or ran something before every input was checked")


@pytest.fixture
def profiled(monkeypatch):
    """Build records name the profile they were published with; replay passes it to the archived run."""
    made = batch.build_record
    monkeypatch.setattr(batch, "build_record", lambda *a, **k: made(*a, **k) | {
        "profile": {"roles": {"other": "may_read", "reader": "may_read"}}})


@pytest.fixture
def case(profiled, inputs, tmp_path, monkeypatch):
    """A committed private candidate and its kept target as a file store, as `check` reads it. The kept target
    is the publication alone: the earlier manifest whose views the checkpoints froze is not part of it."""
    target = {k: v for k, v in inputs["target"].items() if not k.startswith(("p/m-1/", "p/manifests/m-1."))}
    key = inputs["manifest_key"]  # the recorded inputs a replay publishes again with
    target[key] = publish.canonical(json.loads(target[key]) | {
        "epoch": 2, "knowledge_time": "2026-01-01T00:00:00Z", "sources": [{"source_id": "facts", "position": "kept"}]})
    inputs = dict(inputs, target=target)
    receipt = candidates.commit_archive(**inputs)
    kept_root = tmp_path / "kept"
    old = store.FileStore(kept_root)
    for k, body in inputs["target"].items():
        old.put_new(k, body)
    monkeypatch.setattr(kept, "install_python", never)
    monkeypatch.setattr(kept, "install_views", never)
    monkeypatch.setattr(kept, "run_archived", never)
    monkeypatch.setattr(kept_views, "trusted_node", lambda component, node=None: "/pinned/node")
    return dict(inputs, receipt=receipt.directory, old=old, kept_root=kept_root, new_root=tmp_path / "new")


def replay(case, archives="default", seeded=None):
    archives = {case["manifest_key"]: case["receipt"]} if archives == "default" else archives
    return kept.replay(case["pack_dir"], case["old"], case["new_root"], archives, None, seeded)


def recommit(case, change) -> Path:
    """What someone who can write the private location could leave there: the archive's members changed by
    `change`, with a digest and a receipt made consistent again, under the new receipt's hash."""
    receipt = json.loads((case["receipt"] / "receipt.json").read_bytes())
    build = receipt["build_sha256"]
    with tarfile.open(fileobj=io.BytesIO((case["receipt"] / f"{build}.tar.gz").read_bytes())) as tar:
        members = {m.name: tar.extractfile(m).read() for m in tar.getmembers()}
    members = change(members)
    out = io.BytesIO()
    with gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz, tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
        for name, body in sorted(members.items()):
            entry = tarfile.TarInfo(name)
            entry.size, entry.mtime, entry.mode = len(body), 0, 0o644
            tar.addfile(entry, io.BytesIO(body))
    data = out.getvalue()
    pin = kept.digest_line(Path(f"{build}.tar.gz"), data).encode()
    pack, mid = case["manifest_key"].split("/")[0], json.loads(case["old"].get(case["manifest_key"]))["id"]
    receipt["files"] = {f"{build}.tar.gz": {"sha256": sha256_hex(data), "size": str(len(data))},
                        f"{build}.sha256": {"sha256": sha256_hex(pin), "size": str(len(pin))}}
    receipt["captures"] = {
        views.checkpoint_key(pack, mid, unquote(name.rsplit("/", 1)[-1].removesuffix(".json"))):
            {"checkpoint_sha256": sha256_hex(body), "capture_sha256": canonical_sha256(json.loads(body)["capture"])}
        for name, body in members.items() if name.startswith(kept_views.PRIVATE)}
    body = canonical_bytes(receipt)
    directory = case["destination"] / sha256_hex(body)
    directory.mkdir()
    (directory / f"{build}.tar.gz").write_bytes(data)
    (directory / f"{build}.sha256").write_bytes(pin)
    (directory / "receipt.json").write_bytes(body)
    return directory


# ---------------------------------------------------------------------------------------------------- valid replay

@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_a_view_publication_replays_byte_for_byte_from_its_private_candidate(case, monkeypatch):
    checkpoints, target = case["checkpoints"], case["target"]
    record = json.loads(target[kept.key(json.loads(target[case["manifest_key"]])["build"]["uri"])])
    calls = []

    def install_python(tree):
        calls.append(("python", tree.name))

    def install_views(tree, node):
        calls.append(("npm", tree.name, node))
        assert (tree / "viewer" / "package-lock.json").is_file()

    def archived(tree, args, env=None):
        calls.append(("run", args[-1], env))
        # The verified base and every recorded view source, at the paths the archived publisher reads them.
        assert (tree / "pack" / "pack.yaml").is_file() and (tree / "edge/publisher/rezono_publisher/kept.py").is_file()
        for entry in record["views"]["files"]:
            assert sha256_hex((tree / entry["path"]).read_bytes()) == entry["sha256"]
        new = store.FileStore(tree.parent.parent / "store")
        assert {k: new.get(k) for k in checkpoints} == checkpoints  # frozen inputs, never captured again
        # Stands in for the archived publisher on the pinned runtime: it makes the kept publication again.
        for k, body in target.items():
            new.put_new(k, body)

        class Done:
            returncode, stderr = 0, ""
        return Done()

    monkeypatch.setattr(kept, "install_python", install_python)
    monkeypatch.setattr(kept, "install_views", install_views)
    monkeypatch.setattr(kept, "run_archived", archived)
    monkeypatch.setattr(kept, "kept_dir", lambda _: case["kept_root"])
    assert kept.check(case["pack_dir"], view_archives={case["manifest_key"]: case["receipt"]}) == []
    assert [c[0] for c in calls] == ["python", "npm", "run"]
    assert calls[1][2] == "/pinned/node" and calls[2] == ("run", "--views", {"REZONO_NODE": "/pinned/node"})


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
@pytest.mark.parametrize("damage, why", [
    (lambda new, k: new.put_new(k, b"x"), "extra"),  # a view object the kept publication does not hold
    ("checkpoint", "changed a frozen role checkpoint"),
])
def test_the_replay_comparison_names_every_difference(case, monkeypatch, damage, why):
    target, checkpoints = case["target"], case["checkpoints"]

    def archived(tree, args, env=None):
        new = store.FileStore(tree.parent.parent / "store")
        for k, body in target.items():
            new.put_new(k, body)
        if damage == "checkpoint":
            path = new._path(next(iter(checkpoints)))
            path.write_bytes(b"{}")
        else:
            damage(new, "p/m-2/reader/views/extra.json")

        class Done:
            returncode, stderr = 0, ""
        return Done()

    monkeypatch.setattr(kept, "install_python", lambda tree: None)
    monkeypatch.setattr(kept, "install_views", lambda tree, node: None)
    monkeypatch.setattr(kept, "run_archived", archived)
    monkeypatch.setattr(kept, "kept_dir", lambda _: case["kept_root"])
    found = kept.check(case["pack_dir"], view_archives={case["manifest_key"]: case["receipt"]})
    assert found and all(why in f for f in found), found


# ---------------------------------------------------------------------------------------------------- refusals

@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_replay_refuses_missing_inputs_before_installing(case):
    assert "--view-archive" in replay(case, archives={})[0]
    for name in ("receipt.json", next(p.name for p in case["receipt"].iterdir() if p.name.endswith(".tar.gz"))):
        broken = case["destination"] / "copy"
        broken.mkdir(exist_ok=True)
        for p in case["receipt"].iterdir():
            if p.name != name:
                (broken / p.name).write_bytes(p.read_bytes())
        named = broken.rename(case["destination"] / case["receipt"].name.replace(case["receipt"].name[:1], "0" if case["receipt"].name[0] != "0" else "1", 1))
        refused = replay(case, archives={case["manifest_key"]: named})
        assert refused and "view archive not allowed" in refused[0], refused
        for p in named.iterdir():
            p.unlink()
        named.rmdir()
    # A capture member left out of the archive, everything else made consistent again.
    first = next(iter(case["checkpoints"]))
    dropped = recommit(case, lambda m: {k: v for k, v in m.items()
                                        if not (k.startswith(kept_views.PRIVATE) and k.endswith(first.rsplit("/", 1)[-1]))})
    refused = replay(case, archives={case["manifest_key"]: dropped})
    assert refused and "missing or extra" in refused[0], refused


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_replay_refuses_damaged_inputs_before_installing(case):
    build = json.loads((case["receipt"] / "receipt.json").read_bytes())["build_sha256"]
    archive = case["receipt"] / f"{build}.tar.gz"
    data = archive.read_bytes()
    archive.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
    refused = replay(case)
    assert refused and "does not have the bytes its receipt names" in refused[0], refused
    archive.write_bytes(data)
    # A view source changed inside, with the digest and receipt recomputed around it: the build's inventory
    # still names the old bytes.
    edited = recommit(case, lambda m: m | {"viewer/scripts/views.ts": m["viewer/scripts/views.ts"] + b"\n// edited"})
    refused = replay(case, archives={case["manifest_key"]: edited})
    assert refused and "source hash differs" in refused[0], refused
    # A receipt rewritten for another target is not the receipt its directory names.
    (case["receipt"] / "receipt.json").write_bytes((case["receipt"] / "receipt.json").read_bytes() + b" ")
    refused = replay(case)
    assert refused and "not the one its directory names" in refused[0], refused


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_replay_refuses_another_roles_inputs_before_installing(case):
    roles = sorted(k for k in json.loads((case["receipt"] / "receipt.json").read_bytes())["captures"])
    assert len(roles) == 2

    def swap(members):
        a, b = sorted(k for k in members if k.startswith(kept_views.PRIVATE))
        return members | {a: members[b], b: members[a]}

    refused = replay(case, archives={case["manifest_key"]: recommit(case, swap)})
    assert refused and "capture binding differs" in refused[0], refused


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_replay_refuses_another_node_before_installing(case, monkeypatch, tmp_path):
    monkeypatch.undo()  # the real trusted_node, and still nothing may install or run
    monkeypatch.setattr(kept, "install_python", never)
    monkeypatch.setattr(kept, "install_views", never)
    monkeypatch.setattr(kept, "run_archived", never)
    other = executable_file(tmp_path / "node", b"another node")
    refused = kept.replay(case["pack_dir"], case["old"], case["new_root"],
                          {case["manifest_key"]: case["receipt"]}, str(other))
    assert refused and "not the executable the recorded view build names" in refused[0], refused


def executable_file(path: Path, body: bytes) -> Path:
    path = path.with_suffix(".exe") if os.name == "nt" else path
    path.write_bytes(body)
    path.chmod(0o755)
    return path


def test_trusted_node_is_the_recorded_executable_by_digest(tmp_path):
    node = executable_file(tmp_path / "node", b"the recorded node")
    component = {"node": {"executable_sha256": sha256_hex(b"the recorded node")}}
    assert kept_views.trusted_node(component, str(node)) == str(node.resolve())
    node.write_bytes(b"patched")
    with pytest.raises(kept_views.ArchiveError, match="not the executable"):
        kept_views.trusted_node(component, str(node))


@pytest.mark.xfail(strict=True, reason="later: tekenweergaven")
def test_routes_without_a_private_candidate_still_refuse_view_publications(case):
    assert any("view-aware" in e for e in kept.verify(case["pack_dir"], case["old"], case["manifest_key"],
                                                       case["new_root"] / "base-only"))
