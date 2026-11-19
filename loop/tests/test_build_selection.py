"""Compare a checked build publication with the existing selector on the same Git observation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest
import yaml

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


def capture(root, base, head, paths, *, coverage=True):
    records = {
        "build_run": [
            {"id": "current", "event": "pull_request", "base_sha": base, "head_sha": head,
             "engine_sha": ENGINE, "observed_at": OBSERVED_AT, **({"receipt": "receipt"} if coverage else {})}
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
    return records


def published(tmp, records):
    build = tmp / "build"
    shutil.copytree(ROOT / "build", build)
    for pack in ("std-loop", "std-order", "std-decision"):
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


class MissingSelectionReceipt(AssertionError):
    """The build publication narrows the selection without an admitted build-selection receipt."""


# Without an admitted receipt the publication selects full checks, while the Python selector still narrows;
# with a verified receipt the two agree in loop/tests/test_mapped_path_requires_reader_inventory.py.
@pytest.mark.parametrize(("path", "legacy_wanted", "fallback"), [
    ("alpha/engine.py", {"alpha", "beta", "gamma"}, {"missing-selection-receipt"}),
    ("decisions/note.md", set(), {"missing-selection-receipt"}),
    ("unmapped.txt", set(SUITES), {"change", "missing-selection-receipt"}),
])
def test_build_selection_matches_python(tmp_path, path, legacy_wanted, fallback):
    source = tmp_path / "source"
    base, head, paths = repository(source, path)
    assert paths == [path]
    records = capture(source, base, head, paths)
    rows = published(tmp_path, records)

    universe = [components.Component(name, "python") for name in SUITES]
    legacy = {component.folder for component in components.pull_request_components(universe, source, "main")}
    chosen = {row["key"][1] for row in rows["build_selected_job"]}
    assert legacy == legacy_wanted
    reasons = {row["key"][2] for row in rows["build_selected_job"]}
    full = {row["key"][1] for row in rows["build_full_selection"]}
    if chosen != set(SUITES) or full != fallback or reasons != fallback:
        raise MissingSelectionReceipt(f"{path}: selected {sorted(chosen)}, full {rows['build_full_selection']}")
    assert all(row["key"][0] == "current" for row in rows["build_selected_job"])


def test_build_selection_requires_matching_receipt(tmp_path):
    source = tmp_path / "source"
    base, head, paths = repository(source, "alpha/engine.py")
    records = capture(source, base, head, paths)
    records["loop_sweep_receipt"][0]["event_time"] = OBSERVED_AT - 1
    rows = published(tmp_path, records)
    assert {row["key"][1] for row in rows["build_selected_job"]} == set(SUITES)
    assert [row["key"] for row in rows["build_full_selection"]] == [["current", "missing-observation-receipt"]]
