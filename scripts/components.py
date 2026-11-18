#!/usr/bin/env python3
"""Discover repository components from directory structure without a central list."""

from __future__ import annotations

import argparse
from collections import Counter
import re
import json
import os
import shutil
import subprocess
import sys
import tempfile
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
    if event == "merge_group":
        base = os.environ.get("MERGE_GROUP_BASE_SHA", "")
        head = os.environ.get("MERGE_GROUP_HEAD_SHA", "")
        if not all(re.fullmatch(r"[0-9a-f]{40}", sha) for sha in (base, head)):
            return None
        def git(*arguments: str):
            return subprocess.run(["git", *arguments], cwd=root, capture_output=True)
        if git("rev-parse", "HEAD").stdout.decode().strip() != head:
            return None
        if git("merge-base", "--is-ancestor", base, head).returncode:
            return None
        revisions = [base, head]
    elif base_ref:
        # Discovery checks out full history, including the PR's target branch.
        revisions = [f"origin/{base_ref}...HEAD"]
    elif before_sha and re.fullmatch(r"(?!0{40})[0-9a-f]{40}", before_sha):
        revisions = [before_sha, "HEAD"]
    else:
        return None
    result = subprocess.run(
        ["git", "diff", "--no-renames", "--name-only", "-z", *revisions, "--"],
        cwd=root, capture_output=True,
    )
    if result.returncode:
        return None
    return [os.fsdecode(name) for name in result.stdout.split(bytes(1)) if name]


# Unpackaged components consumed by other checks via files or subprocesses,
# including the offline runner's replay of a loop and the loop's admission proof.
# A change to a shared library, fixture tree or unknown component runs everything.
FILE_CONSUMERS = {
    "k8s-admission": ("loop",),
    "loop": ("run",),
    "run": (),
    "deploy/profiles/edge": ("edge/publisher",),
}


def affected_components(
    components: list[Component], changed_files: list[str] | None
) -> list[Component]:
    if changed_files is None:
        return list(components)
    by_folder = {c.folder: c for c in components}
    selected: set[str] = set()
    pending: list[str] = []
    for path in changed_files:
        owner = next((c for c in components if path.startswith(c.folder + "/")), None)
        if owner is None:
            # Markdown, golden files and shared packs are read by component tests.
            return list(components)
        selected.add(owner.folder)
        name = Path(path).name
        if (owner.kind == "contracts" or (ROOT / owner.folder / "pyproject.toml").exists()
                or name in {"pyproject.toml", "package.json", "conftest.py"}):
            return list(components)
        # Tests can themselves be imported as cross-component oracles. Shared
        # source and test roots have no isolation contract, so keep full coverage.
        # The leaf components below use the same file-consumer closure for test
        # entry points and for production inputs.
        pending.append(owner.folder)
    visited: set[str] = set()
    while pending:
        folder = pending.pop()
        if folder in visited:
            continue
        visited.add(folder)
        if folder not in FILE_CONSUMERS:
            return list(components)
        for consumer in FILE_CONSUMERS[folder]:
            if consumer not in by_folder:
                return list(components)
            selected.add(consumer)
            pending.append(consumer)
    return [c for c in components if c.folder in selected]


# Files are assigned to jobs round-robin. Within a job pytest items share the
# runner's cores, so one large parametrized file can use more than one core.
SHARDS = {"compiler": 3, "examples": 5}
PARALLEL = {"compiler", "examples", "edge/publisher"}


def test_files(folder: str) -> list[str]:
    directory = ROOT / folder
    return sorted({
        path.relative_to(ROOT).as_posix()
        for pattern in ("test_*.py", "*_test.py")
        for path in directory.rglob(pattern)
        if path.is_file()
    })


def runner_cores() -> int:
    available = len(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else os.cpu_count()
    return min(4, available or 1)


def check_contracts() -> int:
    # The checker discovers fixtures relative to its own location. Each copy
    # runs the original checker with all schemas and a disjoint fixture set.
    source = ROOT / "contracts"
    fixtures = sorted((source / "fixtures").glob("*/*/*/*.yaml"))
    workers = runner_cores()

    def check(worker: int) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as tmp:
            copy = Path(tmp) / "contracts"
            excluded = set(fixtures) - set(fixtures[worker::workers])

            def ignore(directory: str, names: list[str]) -> list[str]:
                return [name for name in names if Path(directory) / name in excluded]

            shutil.copytree(source, copy, ignore=ignore)
            return subprocess.run(
                ["bash", str(copy / "check.sh")], stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, check=False,
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        status = 0
        for result in pool.map(check, range(workers)):
            print(result.stdout, end="", flush=True)
            status = status or result.returncode
        return status


def inventory_path(directory: Path, folder: str) -> Path:
    return directory / folder / "items.json"


def collect_component(folder: str, directory: Path) -> int:
    import pytest

    sys.path.insert(0, str(ROOT))
    dest = inventory_path(directory, folder)
    dest.parent.mkdir(parents=True, exist_ok=True)
    collection_report = dest.with_name("collection.xml")
    items: list[str] = []
    config_path = None

    class Inventory:
        def pytest_collection_finish(self, session):
            nonlocal config_path
            items.extend(item.nodeid for item in session.items)
            config_path = str(session.config.inipath.relative_to(ROOT)) if session.config.inipath else None

    result = pytest.main(
        [folder, "--collect-only", "-qq", "--rootdir", str(ROOT), f"--junitxml={collection_report}"],
        plugins=[Inventory()],
    )
    if result == pytest.ExitCode.NO_TESTS_COLLECTED:
        # A component without tests is valid only with the original blocked-file evidence.
        if folder == "contracts/python" or subprocess.call(
            [sys.executable, str(ROOT / "scripts/red_list.py"), "--all-tests-blocked", folder]
        ):
            return 1
    elif result:
        return int(result)
    if len(items) != len(set(items)):
        raise ValueError(f"{folder}: duplicate pytest node IDs in the inventory")
    files = sorted(set(test_files(folder)) | {i.split("::", 1)[0] for i in items})
    dest.write_text(json.dumps({"items": items, "files": files, "config": config_path}), encoding="utf-8")
    print(f"{folder}: inventoried {len(items)} node IDs from {len(files)} test files", flush=True)
    return 0


def pytest_folder(component: dict) -> str:
    return component["folder"] + ("/python" if component["kind"] == "contracts" else "")


def collect_matrix(matrix: list[dict], directory: Path) -> int:
    folders = sorted({pytest_folder(c) for c in matrix})
    def collect(folder: str) -> int:
        return subprocess.call([sys.executable, __file__, "collect-component", folder, str(directory)])
    with ThreadPoolExecutor(max_workers=runner_cores()) as pool:
        statuses = list(pool.map(collect, folders))
        return next((code for code in statuses if code), 0)


def shard_items(plan: dict, shard: int, total: int) -> list[str]:
    files = set(plan["files"][shard::total])
    return [node for node in plan["items"] if node.split("::", 1)[0] in files]


def weighted_workers(items: list[str], workers: int, weights: dict[str, int], default: int) -> list[list[str]]:
    """Assign expensive IDs first, resolving ties in inventory order, then retain pytest's order."""
    loads = [0] * workers
    assigned = {}
    for node in sorted(items, key=lambda item: -weights.get(item, default)):
        slot = min(range(workers), key=loads.__getitem__)
        assigned[node] = slot
        loads[slot] += weights.get(node, default)
    groups = [[] for _ in range(workers)]
    for node in items:
        groups[assigned[node]].append(node)
    return groups


def worker_items(folder: str, items: list[str], workers: int) -> list[list[str]]:
    if folder == "compiler" and workers > 1:
        # The profile records calls at or above its threshold from each compiler worker's
        # five reported durations in the linked run. The default is the sum of worker pytest
        # times minus those calls, divided by the remaining IDs, rounded to milliseconds.
        profile = json.loads((ROOT / ".github/workflows/compiler-duration-profile.json").read_text(encoding="utf-8"))
        return weighted_workers(items, workers, profile["call_ms"], profile["default_ms"])
    if folder != "examples" or workers == 1:
        return [items[n::workers] for n in range(workers)]
    # Keep the examples' file-scoped accumulation and the two independent immutable readers.
    forms = "examples/subsidy/test_subsidy_forms.py"
    readers = sorted(i for i in items if i.split("::", 1)[0] == forms)
    groups = [[] for _ in range(workers)]
    offset = 2 if readers and workers > 2 else 0
    if offset:
        # Keep pytest collection order within each execution process.
        first = set(readers[::2])
        for node in items:
            if node in first:
                groups[0].append(node)
            elif node in readers:
                groups[1].append(node)
    others = [i for i in items if not offset or i.split("::", 1)[0] != forms]
    files = sorted({i.split("::", 1)[0] for i in others})
    slots = {f: offset + n % (workers - offset) for n, f in enumerate(files)}
    for node in others:
        groups[slots[node.split("::", 1)[0]]].append(node)
    return groups


def execute_worker(assignment: Path, journal: Path, report: Path) -> int:
    import pytest

    sys.path.insert(0, str(ROOT))
    data = json.loads(assignment.read_text(encoding="utf-8"))
    expected = data["items"]
    with journal.open("w", encoding="utf-8", buffering=1) as evidence:
        if not expected:
            return 0

        class Evidence:
            def pytest_collection_finish(self, session):
                found = [i.nodeid for i in session.items]
                if Counter(found) != Counter(expected):
                    raise pytest.UsageError("The requested pytest IDs resolved to a different set")

            def pytest_runtest_logstart(self, nodeid, location):
                print(json.dumps(["start", nodeid]), file=evidence)

            def pytest_runtest_logfinish(self, nodeid, location):
                print(json.dumps(["finish", nodeid]), file=evidence)

        args = ["-q", "--durations=5", "--rootdir", str(ROOT), f"--junitxml={report}"]
        if data["config"]:
            args.extend(["-c", data["config"]])
        # Pytest resolves only assigned IDs, without walking the component again.
        return int(pytest.main([*args, "--", *expected], plugins=[Evidence()]))


def run_shard(folder: str, shard: int, total: int, plans: Path, reports: Path, receipts: Path) -> int:
    plan = json.loads(inventory_path(plans, folder).read_text(encoding="utf-8"))
    reports.mkdir(parents=True, exist_ok=True)
    evidence = receipts / folder
    evidence.mkdir(parents=True, exist_ok=True)
    selected = shard_items(plan, shard, total)
    groups = worker_items(folder, selected, runner_cores() if folder in PARALLEL else 1)
    if Counter(i for group in groups for i in group) != Counter(selected):
        raise ValueError("Worker assignments differ from the shard inventory")
    print(f"{folder} shard {shard+1}/{total}: {len(selected)} test IDs", flush=True)
    def execute(pair):
        index, nodes = pair
        assignment = reports / f"assignment-{index}.json"
        assignment.write_text(json.dumps({"items": nodes, "config": plan["config"]}), encoding="utf-8")
        return subprocess.call([
            sys.executable, __file__, "execute-worker", str(assignment),
            str(evidence / f"{shard}-{index}.jsonl"), str(reports / f"pytest-{index}.xml"),
        ])
    with ThreadPoolExecutor(max_workers=len(groups)) as pool:
        statuses = list(pool.map(execute, enumerate(groups)))
        status = next((code for code in statuses if code), 0)
    # Write the expected number of journals even on failure, for diagnosis.
    (evidence / f"{shard}.json").write_text(json.dumps(len(groups)), encoding="utf-8")
    return status


def verify_execution(matrix: list[dict], plans: Path, receipts: Path) -> int:
    success = True
    for folder in sorted({pytest_folder(c) for c in matrix}):
        rows = [c for c in matrix if pytest_folder(c) == folder]
        plan = json.loads(inventory_path(plans, folder).read_text(encoding="utf-8"))
        observed = {"start": Counter(), "finish": Counter()}
        for row in rows:
            shard, total = row["shard"], row["total"]
            directory = receipts / folder
            expected = Counter(shard_items(plan, shard, total))
            shard_counts = {"start": Counter(), "finish": Counter()}
            try:
                workers = json.loads((directory / f"{shard}.json").read_text(encoding="utf-8"))
                for index in range(workers):
                    journal = (directory / f"{shard}-{index}.jsonl").read_text(encoding="utf-8")
                    for line in journal.splitlines():
                        event, node = json.loads(line)
                        shard_counts[event][node] += 1
            except (OSError, ValueError, KeyError) as error:
                print(f"{folder} shard {shard+1}: incomplete evidence: {error}", file=sys.stderr)
                success = False
            for event, counts in shard_counts.items():
                observed[event].update(counts)
                if counts != expected:
                    print(f"{folder} shard {shard+1} {event}: missing {list((expected-counts).elements())}, "
                          f"extra {list((counts-expected).elements())}", file=sys.stderr)
                    success = False
        for event, counts in observed.items():
            if counts != Counter(plan["items"]):
                print(f"{folder}: {event} differs from full component inventory", file=sys.stderr)
                success = False
        print(f"{folder}: inventoried {len(plan['items'])}, started {observed['start'].total()}, "
              f"finished {observed['finish'].total()}")
    return 0 if success else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="List discovered component folders and kinds.")
    sub.add_parser("python-packages", help="Print editable Python package directories.")
    sub.add_parser("check-contracts", help="Validate all contract fixtures across runner cores.")
    shard_p = sub.add_parser("run-shard", help="Run the selected pytest file partition.")
    shard_p.add_argument("folder")
    shard_p.add_argument("shard", type=int)
    shard_p.add_argument("total", type=int)
    shard_p.add_argument("plans", type=Path)
    shard_p.add_argument("reports", type=Path)
    shard_p.add_argument("receipts", type=Path)
    collect = sub.add_parser("collect-component")
    collect.add_argument("folder")
    collect.add_argument("plans", type=Path)
    for name in ("inventory", "verify-execution"):
        command = sub.add_parser(name)
        command.add_argument("plans", type=Path)
        if name == "verify-execution":
            command.add_argument("receipts", type=Path)
    worker = sub.add_parser("execute-worker")
    for name in ("assignment", "journal", "report"):
        worker.add_argument(name, type=Path)
    matrix_p = sub.add_parser("ci-matrix", help="Emit GitHub Actions matrix outputs.")
    matrix_p.add_argument("--base-ref", default=os.environ.get("GITHUB_BASE_REF", ""))
    matrix_p.add_argument("--before", default=os.environ.get("GITHUB_EVENT_BEFORE", ""))

    args = parser.parse_args()
    if args.cmd == "check-contracts":
        return check_contracts()
    if args.cmd == "run-shard":
        return run_shard(args.folder, args.shard, args.total, args.plans, args.reports, args.receipts)
    if args.cmd == "inventory":
        return collect_matrix(json.loads(os.environ["PYTHON_MATRIX"]), args.plans)
    if args.cmd == "collect-component":
        return collect_component(args.folder, args.plans)
    if args.cmd == "execute-worker":
        return execute_worker(args.assignment, args.journal, args.report)
    if args.cmd == "verify-execution":
        return verify_execution(json.loads(os.environ["PYTHON_MATRIX"]), args.plans, args.receipts)
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
