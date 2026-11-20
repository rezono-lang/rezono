"""Route collected live comparisons and combine their unchanged JUnit suites."""

import argparse
from collections import Counter
from pathlib import Path
import xml.etree.ElementTree as ET

from verify_feldera_run import PLATFORM_TEST, junit_key


INCREMENTAL = "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch"
EXAMPLE = "examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors"
CALC = "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives"
GENERATED = "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does"
ORDERED_SCALARS = "compiler/tests/test_ordered_rule_scalars_engines.py::test_feldera_orders_typed_values"
INTERFACE = f"{INCREMENTAL}[platform/tenant-capacity/interface]"
BOOLEAN = "compiler/tests/test_boolean_rule_inputs.py::test_native_boolean_rule_inputs"
SHARDS = {
    "library": (f"{EXAMPLE}[library]",),
    "projects": (f"{EXAMPLE}[projects]",),
    "platform": (f"{INCREMENTAL}[platform]", PLATFORM_TEST),
    "tenant-capacity-interface": (INTERFACE,),
    "subsidy": (f"{INCREMENTAL}[subsidy]",),
    "compiler-calc": (f"{CALC}[full]", f"{CALC}[choice]"),
    "compiler-bound": ("compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound",
                       BOOLEAN),
    "compiler-rules": (f"{GENERATED}[0]", f"{GENERATED}[1]", ORDERED_SCALARS),
}
EXPECTED = {node for group in SHARDS.values() for node in group}
ORIGINAL = EXPECTED - {INTERFACE, BOOLEAN, ORDERED_SCALARS}


def collection(path: Path) -> list[str]:
    nodes = path.read_text(encoding="utf-8").splitlines()
    if not nodes or len({junit_key(node) for node in nodes}) != len(nodes):
        raise ValueError(f"{path}: empty or duplicate collected case IDs")
    return nodes


def selection(nodes: list[str], shard: str) -> list[str]:
    if set(nodes) != EXPECTED or len(nodes) != sum(map(len, SHARDS.values())):
        raise ValueError(f"unexpected oracle collection: missing {sorted(EXPECTED - set(nodes))}, "
                         f"extra {sorted(set(nodes) - EXPECTED)}")
    assigned = set(SHARDS[shard])
    return [node for node in nodes if node in assigned]


def combine(shards: Path, output: Path, attempt: int) -> None:
    folders = {shard: shards / f"feldera-shard-{attempt}-{shard}" for shard in SHARDS}
    if set(shards.iterdir()) != set(folders.values()):
        raise ValueError(f"expected exactly {len(SHARDS)} shard artifacts from attempt {attempt}")
    nodes = collection(folders[next(iter(SHARDS))] / "collection.txt")
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
