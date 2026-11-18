"""Route promoted cluster tests using the node IDs in the ordinary CI inventory."""

import argparse
import json
from pathlib import Path
import subprocess

from fast_check import resolve
from red_list import ROOT, extract_red_tests_from_source


def promoted_tasks(base: str, cluster: set[str]) -> list[str]:
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "--diff-filter=M", "-z", base, "HEAD", "--"],
        cwd=ROOT,
    ).decode("utf-8").split("\0")
    cluster_paths = {node.split("::", 1)[0] for node in cluster}
    promoted = set()
    for path in cluster_paths.intersection(changed):
        before = subprocess.check_output(["git", "show", f"{base}:{path}"], cwd=ROOT, encoding="utf-8")
        earlier = {item.id for item in extract_red_tests_from_source(before, path, [])
                   if item.nodeid in cluster}
        after = (ROOT / path).read_text(encoding="utf-8")
        remaining = {item.id for item in extract_red_tests_from_source(after, path, [])}
        promoted.update(earlier - remaining)
    return sorted(promoted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    parser.add_argument("--worker", default="")
    parser.add_argument("--base", default="")
    args = parser.parse_args()
    cluster = {node for path in args.inventory.rglob("items.json")
               for node in json.loads(path.read_text(encoding="utf-8"))["cluster"]}
    if args.worker.startswith("task/"):
        task = args.worker.removeprefix("task/")
        tasks = [task] if resolve(task, args.base) in cluster else []
    elif args.base:
        tasks = promoted_tasks(args.base, cluster)
    else:
        tasks = []
    print(f"tasks={json.dumps(tasks)}")


if __name__ == "__main__":
    main()
