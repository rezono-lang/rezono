"""Route collected live comparisons and combine their unchanged JUnit suites."""

import argparse
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

from verify_feldera_run import PLATFORM_TEST, junit_key


SHARDS = ("compiler-and-examples", "platform", "subsidy")
INCREMENTAL = "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch"


def collection(path: Path) -> list[str]:
    nodes = path.read_text(encoding="utf-8").splitlines()
    if not nodes or len({junit_key(node) for node in nodes}) != len(nodes):
        raise ValueError(f"{path}: empty or duplicate collected case IDs")
    return nodes


def group(node: str) -> str:
    if not node.startswith(("compiler/tests/", "examples/")):
        raise ValueError(f"unexpected oracle test path: {node}")
    if node in {f"{INCREMENTAL}[platform]", PLATFORM_TEST}:
        return "platform"
    if node == f"{INCREMENTAL}[subsidy]":
        return "subsidy"
    return "compiler-and-examples"


def selection(nodes: list[str], shard: str) -> list[str]:
    selected = [node for node in nodes if group(node) == shard]
    if not selected:
        raise ValueError(f"{shard}: no matching cases in the full collection")
    return selected


def combine(shards: Path, output: Path, attempt: int) -> None:
    folders = {shard: shards / f"feldera-shard-{attempt}-{shard}" for shard in SHARDS}
    if set(shards.iterdir()) != set(folders.values()):
        raise ValueError(f"expected exactly the three shard artifacts from attempt {attempt}")
    nodes = collection(folders[SHARDS[0]] / "collection.txt")
    report = ET.Element("testsuites", name="Live Feldera comparison")
    for shard, folder in folders.items():
        if set(collection(folder / "collection.txt")) != set(nodes):
            raise ValueError(f"{shard}: full pytest collections disagree")
        assigned = selection(nodes, shard)
        if set(collection(folder / "collected.txt")) != set(assigned):
            raise ValueError(f"{shard}: recorded cases differ from the assigned cases")
        suite = ET.parse(folder / "results.xml").getroot()
        if suite.tag not in {"testsuites", "testsuite"}:
            raise ValueError(f"{shard}: invalid JUnit root: {suite.tag!r}")
        actual = Counter((case.get("classname"), case.get("name")) for case in suite.iter("testcase"))
        if actual != Counter(map(junit_key, assigned)):
            raise ValueError(f"{shard}: JUnit cases differ from the assigned cases")
        report.extend(suite if suite.tag == "testsuites" else [suite])

    output.mkdir(parents=True, exist_ok=True)
    (output / "collected.txt").write_text("\n".join(nodes) + "\n", encoding="utf-8")
    ET.ElementTree(report).write(output / "results.xml", encoding="utf-8", xml_declaration=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    select = commands.add_parser("select")
    select.add_argument("shard", choices=SHARDS)
    select.add_argument("collection", type=Path)
    merge = commands.add_parser("merge")
    merge.add_argument("shards", type=Path)
    merge.add_argument("output", type=Path)
    merge.add_argument("attempt", type=int)
    args = parser.parse_args()
    try:
        if args.command == "select":
            print("\n".join(selection(collection(args.collection), args.shard)))
        else:
            combine(args.shards, args.output, args.attempt)
    except (OSError, ValueError, ET.ParseError) as error:
        parser.exit(1, f"ERROR {error}\n")


if __name__ == "__main__":
    main()
