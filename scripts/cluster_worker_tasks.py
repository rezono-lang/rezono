"""Route assigned cluster tests or the full suite from a candidate's changes."""

import argparse
import ast
import json
import os
from pathlib import Path, PurePosixPath
import subprocess

from fast_check import resolve
from red_list import ROOT, extract_red_tests_from_source


CLUSTER_WORKFLOW = ".github/workflows/disposable-cluster.yml"
CLUSTER_DIRS = ("loop/", "packs/std-loop/")


def git(*args: str) -> bytes:
    return subprocess.check_output(["git", *args], cwd=ROOT)


def needs_fixture(node: str, cluster: set[str]) -> bool:
    return node in cluster or any(item.startswith(node + "[") for item in cluster)


def promoted_tasks(base: str, cluster: set[str]) -> list[str]:
    changed = {
        os.fsdecode(path) for path in git("diff", "--no-renames", "--name-only", "--diff-filter=M",
                                         "-z", base, "HEAD", "--").split(b"\0") if path
    }
    cluster_paths = {node.split("::", 1)[0] for node in cluster}
    promoted = set()
    for path in cluster_paths.intersection(changed):
        before = git("show", f"{base}:{path}").decode("utf-8")
        earlier = {item.id for item in extract_red_tests_from_source(before, path, [])
                   if needs_fixture(item.nodeid, cluster)}
        after = git("show", f"HEAD:{path}").decode("utf-8")
        remaining = {item.id for item in extract_red_tests_from_source(after, path, [])}
        promoted.update(earlier - remaining)
    return sorted(promoted)


def declares_cluster_mark(source: bytes, path: str) -> bool:
    """Find the repository's authored pytest mark in a test from either Git tree."""
    tree = ast.parse(source, filename=path)
    nodes = list(ast.walk(tree))
    pytest_names = {"pytest"}
    mark_names = set()
    for node in nodes:
        if isinstance(node, ast.Import):
            pytest_names.update(name.asname or name.name for name in node.names if name.name == "pytest")
        if isinstance(node, ast.ImportFrom) and node.module == "pytest" and node.level == 0:
            mark_names.update(name.asname or name.name for name in node.names if name.name == "mark")
    for node in nodes:
        if not isinstance(node, ast.Attribute) or node.attr != "cluster":
            continue
        owner = node.value
        if isinstance(owner, ast.Name) and owner.id in mark_names:
            return True
        if isinstance(owner, ast.Attribute) and owner.attr == "mark":
            if isinstance(owner.value, ast.Name) and owner.value.id in pytest_names:
                return True
    return False


def touches_fixture(base: str, cluster: set[str]) -> bool:
    # Treat a rename as deletion plus addition. Inspect the source and destination
    # in their own trees, including a mark that disappears in the new file.
    changes = git("diff", "--no-renames", "--name-status", "-z", base, "HEAD", "--").split(b"\0")[:-1]
    paths = {node.split("::", 1)[0] for node in cluster}
    for status, raw_path in zip(changes[::2], changes[1::2], strict=True):
        path = os.fsdecode(raw_path)
        if path.startswith(CLUSTER_DIRS) or path == CLUSTER_WORKFLOW or path in paths:
            return True
        name = PurePosixPath(path).name
        if not (name.startswith("test_") and name.endswith(".py") or name.endswith("_test.py")):
            continue
        if status != b"A" and declares_cluster_mark(git("show", f"{base}:{path}"), path):
            return True
        if status != b"D" and declares_cluster_mark(git("show", f"HEAD:{path}"), path):
            return True
    return False


def route(cluster: set[str], *, worker: str = "", base: str = "", diff_base: str = "") -> tuple[str, list[str]]:
    if diff_base:
        diff_base = git("rev-parse", "--verify", "--end-of-options", f"{diff_base}^{{commit}}").decode().strip()
        git("merge-base", "--is-ancestor", diff_base, "HEAD")
    if worker.startswith("task/"):
        task = worker.removeprefix("task/")
        tasks = [task] if needs_fixture(resolve(task, base or diff_base or "origin/main"), cluster) else []
    elif base:
        tasks = promoted_tasks(base, cluster)
    else:
        tasks = []
    if tasks:
        return "tasks", tasks
    if diff_base and touches_fixture(diff_base, cluster):
        return "suite", []
    return "none", []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--worker", default="")
    parser.add_argument("--base", default="")
    parser.add_argument("--diff-base", default="", help="Enable full-suite routing for changes against this candidate base")
    args = parser.parse_args()
    cluster = {node for path in args.inventory.rglob("items.json")
               for node in json.loads(path.read_text(encoding="utf-8"))["cluster"]}
    mode, tasks = route(cluster, worker=args.worker, base=args.base, diff_base=args.diff_base)
    print(f"mode={mode}")
    print("tasks=" + ("" if mode == "suite" else json.dumps(tasks)))


if __name__ == "__main__":
    main()
