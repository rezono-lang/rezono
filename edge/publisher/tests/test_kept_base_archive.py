"""A viewless kept target made through --make; only the input batch epoch is supplied."""

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from rezono_canon import canonical_sha256
from rezono_compiler import pack as packs
from rezono_publisher import batch, kept, publish, store
from test_publish import epoch


def digest(data):
    return hashlib.sha256(data).hexdigest()


def tree_digest(files):
    return digest("".join(f"{name}\0{digest(body)}\n" for name, body in sorted(files.items())).encode())


@pytest.fixture
def target(tmp_path, monkeypatch):
    root = tmp_path / "source"
    pack = tmp_path / "toy"
    pack.mkdir()
    pack_bytes = b"name: toy\nimports: []\n"
    (pack / "pack.yaml").write_bytes(pack_bytes)
    expected = {"pack/pack.yaml": pack_bytes}
    install, parts = {}, {}
    for component, directory in [("admission", "admission"), ("canon", "canon"), ("checker", "checker"),
                                 ("compiler", "compiler"), ("publisher", "edge/publisher")]:
        project = f"{directory}/pyproject.toml"
        expected[project] = b"# fixture project\n"
        install[project] = digest(expected[project])
        source = f"{directory}/rezono_{component}/example.py"
        expected[source] = b"# synthetic component\n"
        parts[component] = tree_digest({"example.py": expected[source]})
    expected["contracts/sample.yaml"] = b"name: sample\n"
    expected["requirements/deps.txt"] = b"# empty fixture lock\n"
    for name in (".python-artifact", ".python-digest", ".python-version"):
        expected[f"requirements/{name}"] = (packs.CONTRACTS.parent / "requirements" / name).read_bytes()
    for name, body in expected.items():
        if name.startswith("pack/"):
            continue
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    compiler = {k: parts[k] for k in ("compiler", "admission", "canon")}
    compiler["contracts"] = {"sample.yaml": digest(expected["contracts/sample.yaml"])}
    record = {"format": "rezono.build/3", "install": install, "compiler": compiler,
              "compiler_sha256": canonical_sha256(compiler), "publisher": parts["publisher"], "checker": parts["checker"],
              "locks": {"deps.txt": digest(expected["requirements/deps.txt"])},
              "python": {"version": expected["requirements/.python-version"].decode().strip()}}
    fixture = epoch(build=record, pack_sha256=tree_digest({"pack.yaml": pack_bytes}),
                    compiler_sha256=record["compiler_sha256"], nodes=["amber", "blue"], edges=[], salaries=[],
                    roles=("viewer",), grants=[("viewer", "amber")])
    monkeypatch.setattr(packs, "CONTRACTS", root / "contracts")
    monkeypatch.setattr(batch, "epoch", lambda *args, **kwargs: fixture)
    assert kept.main([str(pack), "--make"]) == 0
    return pack, expected, store.FileStore(pack / "expected/published")


KEY = "toy/manifests/m-1.json"


def test_viewless_base_inventory_and_role_snapshots(target, tmp_path):
    pack, expected, st = target
    manifest = json.loads(st.get(KEY))
    assert publish.newest_main(st, "toy") == manifest
    assert (manifest["id"], manifest["epoch"]) == ("m-1", 1)
    nodes = {s["role"]: s for s in manifest["snapshots"] if s["relation"] == "node"}
    assert set(nodes) == {"checker", "viewer"}
    for role, body in [("checker", b'[\n{"key":["amber"]},\n{"key":["blue"]}\n]\n'),
                       ("viewer", b'[\n{"key":["amber"]}\n]\n')]:
        pin = digest(body)
        key = f"toy/objects/{pin}.json"
        assert (nodes[role]["uri"], nodes[role]["sha256"], nodes[role]["complete"]) == (
            st.uri(key), pin, role == "checker")
        assert st.get(key) == body
    build = manifest["build"]["sha256"]
    assert digest(st.get(f"toy/builds/{build}.json")) == build
    directory = pack / "expected/kept-source"
    data = (directory / f"{build}.tar.gz").read_bytes()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
        assert archive.getnames() == sorted(expected)
        for name, body in expected.items():
            assert archive.extractfile(name).read() == body
    assert (directory / f"{build}.sha256").read_text() == f"{digest(data)}  {build}.tar.gz\n"
    out = tmp_path / "verified"
    assert kept.verify(pack, st, KEY, out) == []
    assert {p.relative_to(out).as_posix(): p.read_bytes() for p in out.rglob("*") if p.is_file()} == expected


def test_an_incomplete_store_names_the_missing_role_snapshot(target, tmp_path):
    pack, _, st = target
    partial = store.FileStore(tmp_path / "partial")
    missing = "toy/objects/" + digest(b'[\n{"key":["amber"]}\n]\n') + ".json"
    for key in st.list(""):
        if key != missing:
            partial.put_new(key, st.get(key))
    out = tmp_path / "verified"
    assert any(st.uri(missing) in error and "named in the manifest, not kept" in error
               for error in kept.verify(pack, partial, KEY, out))
    assert not out.exists()
