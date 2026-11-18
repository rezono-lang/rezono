"""Compare a checked build publication with the existing selector on the same Git observation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

from loop.build_selection_receipt import seal_selection_inventory, verify_selection_inventory
from rezono_compiler import pack
from rezono_publisher import batch, publish, store
from scripts import components


ROOT = Path(__file__).resolve().parents[2]
SUITES = ("alpha", "beta", "gamma", "spare")
OBSERVED_AT = 1_800_000_000
ENGINE = "f" * 40  # Protected-main pin in this isolated replay.


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "core.autocrlf=false", "-c", "user.name=Build fixture",
         "-c", "user.email=build@example.org", *args], cwd=root, text=True, stderr=subprocess.PIPE,
    ).strip()


def repository(root, path):
    root.mkdir()
    git(root, "init", "-q")
    for name, required in zip(SUITES, ([], ["alpha"], ["beta"], []), strict=True):
        directory = root / name
        directory.mkdir()
        (directory / "pyproject.toml").write_text(
            "[project]\nname = " + json.dumps(name) + '\nversion = "0.1.0"\ndependencies = '
            + json.dumps(required) + "\n", encoding="utf-8",
        )
        (directory / "test_unit.py").write_bytes(b"def test_unit():\n    assert True\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Record component inventory")
    git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    changed = root / path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_bytes(b"# changed\n")
    git(root, "add", ".")
    git(root, "commit", "-qm", "Observe one changed path")
    return components.pull_request_range(root, "main")


def capture(root, base, head, paths):
    records = {
        "build_run": [
            {"id": "current", "event": "pull_request", "base_sha": base, "head_sha": head,
             "engine_sha": ENGINE, "observed_at": OBSERVED_AT, "receipt": "receipt"}
        ],
        "loop_sweep_receipt": [{"id": "receipt", "run": "current", "event_time": OBSERVED_AT}],
        "build_component": [{"id": name, "run": "current", "kind": "python", "folder": name} for name in SUITES],
        "build_manifest": [
            {"id": f"{end}-{name}", "component": name, "path": f"{name}/pyproject.toml", "revision": revision,
             "blob": git(root, "rev-parse", f"{revision}:{name}/pyproject.toml")}
            for end, revision in (("base", base), ("head", head)) for name in SUITES
        ],
        "build_test_file": [{"id": name + "-test", "component": name, "path": f"{name}/test_unit.py"} for name in SUITES],
        "build_dependency": [
            {"id": f"{end}-{consumer}-dependency", "dependency": dependency, "consumer": consumer,
             "kind": "manifest", "manifest": f"{end}-{consumer}", "source": f"{consumer}/pyproject.toml"}
            for end in ("base", "head") for consumer, dependency in (("beta", "alpha"), ("gamma", "beta"))
        ],
        "build_path": [
            {"id": "change", "run": "current", "path": path,
             "coverage": "mapped" if path.startswith(("alpha/", "decisions/")) else "unknown"}
            for path in paths
        ],
        "build_path_reader": [
            {"id": "owner", "path": "change", "component": "alpha", "kind": "transitive", "source": "alpha"}
            for path in paths if path.startswith("alpha/")
        ],
    }
    return seal_selection_inventory(pack.read(ROOT / "build"), records)


def published(tmp, records):
    build = tmp / "build"
    shutil.copytree(ROOT / "build", build)
    for pack in ("std-loop", "std-order"):
        shutil.copytree(ROOT / "packs" / pack, tmp / "packs" / pack)
    (build / "facts").mkdir()
    (build / "facts" / "input.yaml").write_text(yaml.safe_dump(records), encoding="utf-8")
    epoch = batch.epoch(build, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=[("facts", "input")])
    archive = store.FileStore(tmp / "archive")
    manifest = publish.publish(epoch, archive, {"reader": "complete"})

    def read(entry):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        return json.loads(data)

    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])
    rows = {entry["relation"]: read(entry) for entry in manifest["snapshots"] if entry["role"] == "reader"}
    return rows


@pytest.mark.parametrize(("path", "wanted", "fallback"), [
    ("alpha/engine.py", {"alpha", "beta", "gamma"}, set()),
    ("decisions/note.md", set(), set()),
    ("unmapped.txt", set(SUITES), {"change"}),
])
def test_build_selection_matches_python(tmp_path, path, wanted, fallback):
    source = tmp_path / "source"
    base, head, paths = repository(source, path)
    assert paths == [path]
    records = capture(source, base, head, paths)
    rows = published(tmp_path, records)
    verify_selection_inventory(records, lambda relation: {tuple(row["key"]) for row in rows[relation]})

    universe = [components.Component(name, "python") for name in SUITES]
    legacy = {component.folder for component in components.pull_request_components(universe, source, "main")}
    chosen = {row["key"][1] for row in rows["build_selected_job"]}
    assert chosen == legacy == wanted
    assert {row["key"][1] for row in rows["build_full_selection"]} == fallback
    assert all(row["key"][0] == "current" and row["key"][2] == "change" for row in rows["build_selected_job"])


def test_build_selection_requires_matching_receipt(tmp_path):
    source = tmp_path / "source"
    base, head, paths = repository(source, "alpha/engine.py")
    records = capture(source, base, head, paths)
    records["loop_sweep_receipt"][0]["event_time"] = OBSERVED_AT - 1
    rows = published(tmp_path, records)
    assert {row["key"][1] for row in rows["build_selected_job"]} == set(SUITES)
    assert [row["key"] for row in rows["build_full_selection"]] == [["current", "missing-observation-receipt"]]


@pytest.mark.parametrize(("path", "change"), [
    ("alpha/engine.py", "omit-reader"),
    ("alpha/engine.py", "add-reader"),
    ("alpha/engine.py", "replace-reader"),
    ("alpha/engine.py", "omit-dependency"),
    ("decisions/note.md", "add-reader"),
    ("decisions/note.md", "omit-cover"),
])
def test_build_selection_requires_exact_receipted_inventory(tmp_path, path, change):
    source = tmp_path / "source"
    base, head, paths = repository(source, path)
    trusted = capture(source, base, head, paths)
    records = deepcopy(trusted)
    if change == "omit-reader":
        records["build_path_reader"].clear()
    elif change == "omit-dependency":
        records["build_dependency"] = [edge for edge in records["build_dependency"] if edge["consumer"] != "gamma"]
    elif change == "replace-reader":
        records["build_path_reader"][0]["component"] = "spare"
    elif change == "omit-cover":
        records["period_close"].clear()
    else:
        records["build_path_reader"].append({"id": "extra", "path": "change", "component": "spare",
                                             "kind": "direct", "source": "declared reader"})

    rows = published(tmp_path, records)
    reason = "unverified-selection-inventory"
    assert [row["key"] for row in rows["build_full_selection"]] == [["current", reason]]
    assert {tuple(row["key"]) for row in rows["build_selected_job"]} == {("current", suite, reason) for suite in SUITES}
    with pytest.raises(ValueError, match="protected selection inventory"):
        verify_selection_inventory(trusted, lambda relation: {tuple(row["key"]) for row in rows[relation]})


@pytest.mark.parametrize(("field", "replacement"), [
    ("observed_at", OBSERVED_AT + 60),
    ("base_sha", "b" * 40),
    ("head_sha", "c" * 40),
    ("engine_sha", "d" * 40),
    ("event", "merge_group"),
])
def test_build_selection_requires_the_receipted_run_identity(tmp_path, field, replacement):
    source = tmp_path / "source"
    base, head, paths = repository(source, "alpha/engine.py")
    trusted = capture(source, base, head, paths)
    submitted = deepcopy(trusted)
    submitted["build_run"][0][field] = replacement
    if field == "observed_at":
        submitted["loop_sweep_receipt"][0]["event_time"] = replacement
    rows = published(tmp_path, submitted)
    assert any(row["key"] == ["current", "unverified-selection-inventory"] for row in rows["build_full_selection"])
    assert {row["key"][1] for row in rows["build_selected_job"]} == set(SUITES)
    with pytest.raises(ValueError, match="protected selection inventory"):
        verify_selection_inventory(trusted, lambda relation: {tuple(row["key"]) for row in rows[relation]})


@pytest.mark.parametrize("altered", ["reader", "suite"])
def test_build_selection_verifier_compares_the_protected_receipt(tmp_path, altered):
    source = tmp_path / "source"
    base, head, paths = repository(source, "alpha/engine.py")
    trusted = capture(source, base, head, paths)
    other = deepcopy(trusted)
    del other["period_close"], other["build_selection_cut"]
    if altered == "reader":
        other["build_path_reader"][0]["component"] = "spare"
        expected = {"spare"}
    else:
        other["build_component"][0]["kind"] = "node"
        expected = {"alpha", "beta", "gamma"}
    rows = published(tmp_path, seal_selection_inventory(pack.read(ROOT / "build"), other))
    assert {row["key"][1] for row in rows["build_selected_job"]} == expected
    with pytest.raises(ValueError, match="protected selection inventory"):
        verify_selection_inventory(trusted, lambda relation: {tuple(row["key"]) for row in rows[relation]})
