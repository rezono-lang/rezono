#!/usr/bin/env python3
"""Discover repository components from directory structure without a central list."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SKIP_DIRS = {
    ".basedpyright",
    ".git",
    ".github",
    ".hypothesis",
    ".pytest_cache",
    ".venv",
    "LICENSES",
    "__pycache__",
    "blocked",
    "build",
    "compiled",
    "dist",
    "docs",
    "generated",
    "node_modules",
    "requirements",
    "scripts",
    "target",
    "to-port",
}


@dataclass(frozen=True)
class Component:
    folder: str
    kind: str  # "contracts" | "python" | "node"


def _has_py_tests(directory: Path) -> bool:
    if any(directory.glob("test_*.py")) or any(directory.glob("*_test.py")):
        return True
    tests_dir = directory / "tests"
    return tests_dir.is_dir() and (
        any(tests_dir.glob("test_*.py")) or any(tests_dir.glob("*_test.py"))
    )


def _has_node_test_script(pkg_json: Path) -> bool:
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    scripts = data.get("scripts")
    return isinstance(scripts, dict) and bool(scripts.get("test"))


def discover_components(root: Path = ROOT) -> list[Component]:
    found: list[Component] = []

    def walk(current: Path, depth: int) -> None:
        if depth > 3:
            return
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            rel = child.relative_to(root).as_posix()
            pkg_json = child / "package.json"
            if pkg_json.is_file() and _has_node_test_script(pkg_json):
                found.append(Component(folder=rel, kind="node"))
                continue
            if (child / "check.sh").is_file() and (child / "gen-types.sh").is_file():
                found.append(Component(folder=rel, kind="contracts"))
                continue
            if (child / "pyproject.toml").is_file() or _has_py_tests(child):
                found.append(Component(folder=rel, kind="python"))
                continue
            walk(child, depth + 1)

    walk(root, 1)
    return sorted(found, key=lambda c: c.folder)


def discover_python_packages(root: Path = ROOT) -> list[str]:
    packages: list[str] = []

    def walk(current: Path, depth: int) -> None:
        if depth > 3:
            return
        for child in sorted(current.iterdir(), key=lambda p: p.name):
            if not child.is_dir() or child.name.startswith(".") or child.name in SKIP_DIRS:
                continue
            if (child / "pyproject.toml").is_file():
                packages.append(child.relative_to(root).as_posix())
                continue
            walk(child, depth + 1)

    walk(root, 1)
    return sorted(packages)


def _git_changed_files(root: Path, base_ref: str | None, before_sha: str | None) -> list[str] | None:
    """Return changed file paths relative to root, or None when everything must run."""
    event = os.environ.get("GITHUB_EVENT_NAME", "")
    if event == "workflow_dispatch":
        return None
    if base_ref:
        subprocess.run(
            ["git", "fetch", "--no-tags", "--depth=50", "origin", base_ref],
            cwd=root,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        res = subprocess.run(
            ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
        return None
    if before_sha and set(before_sha) != {"0"}:
        res = subprocess.run(
            ["git", "diff", "--name-only", before_sha, "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode == 0:
            return [line.strip() for line in res.stdout.splitlines() if line.strip()]
    return None


def affected_components(
    components: list[Component], changed_files: list[str] | None
) -> list[Component]:
    if changed_files is None:
        return list(components)
    if not changed_files:
        return []

    selected: set[str] = set()
    run_all = False
    for path in changed_files:
        if path.startswith("to-port/") or path.endswith(".md"):
            continue
        matched = [
            c.folder
            for c in components
            if path == c.folder or path.startswith(c.folder + "/")
        ]
        if matched:
            for folder in matched:
                selected.add(folder)
                comp = next(c for c in components if c.folder == folder)
                if comp.kind == "contracts":
                    for other in components:
                        if other.kind in ("contracts", "python"):
                            selected.add(other.folder)
        else:
            run_all = True
            break

    if run_all:
        return list(components)
    return [c for c in components if c.folder in selected]


# Files are assigned to jobs round-robin. Within a job pytest items share the
# runner's cores, so one large parametrized file can use more than one core.
SHARDS = {"compiler": 3, "examples": 2}
PARALLEL = {"compiler", "examples", "edge/publisher"}


def test_files(folder: str) -> list[str]:
    directory = ROOT / folder
    return sorted({
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in directory.rglob(pattern)
        if path.is_file()
    })


def run_shard(folder: str, shard: int, total: int, report_dir: Path) -> int:
    files = test_files(folder)
    assigned = files[shard::total]
    print(f"{folder} shard {shard + 1}/{total}: {json.dumps(assigned)}", flush=True)
    ignores = [f"--ignore={path}" for path in files if path not in assigned]
    cores = min(4, len(os.sched_getaffinity(0))) if hasattr(os, "sched_getaffinity") else 1
    workers = cores if folder in PARALLEL else 1
    report_dir.mkdir(parents=True, exist_ok=True)

    def execute(worker: int) -> int:
        args = [
            sys.executable, str(Path(__file__).resolve()), "pytest-worker", folder,
            str(worker), str(workers), str(report_dir), *ignores,
        ]
        return subprocess.run(args, cwd=ROOT, check=False).returncode

    with ThreadPoolExecutor(max_workers=workers) as pool:
        statuses = list(pool.map(execute, range(workers)))
    if all(code == 5 for code in statuses):
        blocked = {
            entry.read_text(encoding="utf-8").split(":", 1)[0].strip()
            for entry in (ROOT / "blocked").glob("*.txt")
        }
        return 0 if files and set(files) <= blocked else 5
    return next((code for code in statuses if code), 0)


def pytest_worker(folder: str, worker: int, workers: int, reports: str, ignores: list[str]) -> int:
    import pytest

    class Partition:
        had_items = False

        @pytest.hookimpl(trylast=True)
        def pytest_collection_modifyitems(self, items):
            self.had_items = bool(items)
            items[:] = items[worker::workers]

    partition = Partition()
    report = Path(reports) / f"pytest-{worker}.xml"
    args = ["-q", "--durations=5", f"--junitxml={report}", *ignores, folder]
    status = pytest.main(args, plugins=[partition])
    if status == pytest.ExitCode.NO_TESTS_COLLECTED and partition.had_items:
        return 0
    return int(status)


def main() -> int:
    if sys.argv[1:2] == ["pytest-worker"]:
        folder, worker, workers, reports, *ignores = sys.argv[2:]
        return pytest_worker(folder, int(worker), int(workers), reports, ignores)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List discovered component folders and kinds.")
    sub.add_parser("python-packages", help="Print editable Python package directories.")
    shard_p = sub.add_parser("run-shard", help="Run the selected pytest file partition.")
    shard_p.add_argument("folder")
    shard_p.add_argument("shard", type=int)
    shard_p.add_argument("total", type=int)
    shard_p.add_argument("reports", type=Path)
    matrix_p = sub.add_parser("ci-matrix", help="Emit GitHub Actions matrix outputs.")
    matrix_p.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", ""))
    matrix_p.add_argument("--before", default=os.environ.get("GITHUB_EVENT_BEFORE", ""))

    args = parser.parse_args()
    if args.cmd == "run-shard":
        return run_shard(args.folder, args.shard, args.total, args.reports)
    if args.cmd == "list":
        for comp in discover_components():
            print(f"{comp.folder}\t{comp.kind}")
        return 0
    if args.cmd == "python-packages":
        print(" ".join(discover_python_packages()))
        return 0
    if args.cmd == "ci-matrix":
        comps = discover_components()
        changed = _git_changed_files(
            ROOT,
            args.base_ref or None,
            args.before or None,
        )
        active = affected_components(comps, changed)
        py_items = [
            {"folder": c.folder, "kind": c.kind, "shard": shard, "total": total,
             "label": c.folder if total == 1 else f"{c.folder} {shard + 1}/{total}"}
            for c in active
            if c.kind in ("contracts", "python")
            for total in [min(SHARDS.get(c.folder, 1), max(1, len(test_files(c.folder))))]
            for shard in range(total)
        ]
        node_items = [
            {"folder": c.folder, "kind": c.kind}
            for c in active
            if c.kind == "node"
        ]
        editable_flags = " ".join(f"-e {pkg}" for pkg in discover_python_packages())
        lines = [
            f"python={json.dumps(py_items, separators=(',', ':'))}",
            f"has_python={'true' if py_items else 'false'}",
            f"node={json.dumps(node_items, separators=(',', ':'))}",
            f"has_node={'true' if node_items else 'false'}",
            f"python_editable={editable_flags}",
        ]
        out_path = os.environ.get("GITHUB_OUTPUT")
        if out_path:
            with open(out_path, "a", encoding="utf-8") as fh:
                for line in lines:
                    fh.write(line + "\n")
        for line in lines:
            print(line)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
