"""Require exactly one passing JUnit entry per collected live Feldera case."""

import argparse
from collections import Counter
from pathlib import Path
import sys
import xml.etree.ElementTree as ET


LIVE_COMPILER_TESTS = {
    "compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound",
    "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives",
    "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does",
}
PLATFORM_TEST = (
    "examples/test_platform_incremental_proof.py"
    "::test_platform_incremental_delta_and_witnesses_match_batch"
)


def junit_key(node: str) -> tuple[str, str]:
    # Pytest preserves the parameter ID verbatim, even when it contains '::'.
    address, bracket, parameter = node.partition("[")
    path, *names = address.split("::")
    if not path.endswith(".py") or not names or not all(names) or (bracket and not parameter.endswith("]")):
        raise ValueError(f"invalid collected node ID: {node!r}")
    classname = ".".join([path.removesuffix(".py").replace("/", "."), *names[:-1]])
    return classname, names[-1] + bracket + parameter


def verify(selection: Path, report: Path) -> list[str]:
    return check_cases(selection.read_text(encoding="utf-8").splitlines(), ET.parse(report).getroot())


def check_cases(nodes: list[str], root: ET.Element) -> list[str]:
    if PLATFORM_TEST not in nodes or LIVE_COMPILER_TESTS.isdisjoint(node.partition("[")[0] for node in nodes):
        raise ValueError("selection needs the platform delta test and a live compiler case")

    expected = {}
    for node in nodes:
        key = junit_key(node)
        if key in expected:
            raise ValueError(f"duplicate collected case: {node!r}")
        expected[key] = node

    if root.tag not in {"testsuites", "testsuite"}:
        raise ValueError(f"invalid JUnit report root: {root.tag!r}")

    failures = []
    seen = Counter()
    for case in root.iter("testcase"):
        key = case.get("classname", ""), case.get("name", "")
        seen[key] += 1
        if key not in expected:
            failures.append(f"unexpected JUnit case: {key!r}")
        else:
            node = expected[key]
            if seen[key] > 1:
                failures.append(f"duplicate JUnit case: {node}")
            for outcome in ("skipped", "failure", "error"):
                if case.find(outcome) is not None:
                    failures.append(f"{outcome}: {node}")
    failures.extend(f"missing JUnit case: {node}" for key, node in expected.items() if key not in seen)
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("selection", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    try:
        failures = verify(args.selection, args.report)
    except (OSError, ValueError, ET.ParseError) as error:
        failures = [str(error)]
    for failure in failures:
        print(f"ERROR {failure}", file=sys.stderr)
    return int(bool(failures))


if __name__ == "__main__":
    sys.exit(main())
