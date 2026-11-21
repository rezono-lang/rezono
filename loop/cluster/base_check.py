"""Run added cluster tests from a selection file on the base source."""

import argparse
from pathlib import Path
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from pytest import ExitCode

# Import red_before from beside this file (isolated CI policy dir) or from scripts/.
_HERE = Path(__file__).resolve().parent
for _candidate in (_HERE, *([_HERE.parents[1] / "scripts"] if len(_HERE.parents) > 1 else [])):
    if (_candidate / "red_before.py").is_file():
        if sys.path[:1] != [str(_candidate)]:
            sys.path.insert(0, str(_candidate))
        break

import red_before

CLUSTER_SKIP_FAILURE = "Skipped cluster test: "


def read_selection(selection: Path) -> list[str]:
    """Read non-empty pytest node IDs from `selection`, failing closed on read errors."""
    try:
        return red_before.read_selection(selection)
    except (OSError, UnicodeError) as exc:
        raise SystemExit(f"ERROR cannot read selection file {selection}: {exc}") from exc


def _is_cluster_skip(element: ET.Element) -> bool:
    """Return True when a JUnit failure or error records a skipped cluster test."""
    text = element.text or ""
    message = element.attrib.get("message", "")
    return (
        text.startswith(CLUSTER_SKIP_FAILURE)
        or message.startswith(CLUSTER_SKIP_FAILURE)
        or f'"{CLUSTER_SKIP_FAILURE}' in message
    )


def parse_outcomes(report: Path) -> tuple[int, int, int]:
    """Count (passed, failed, skipped) test cases in a pytest JUnit XML report."""
    passed = failed = skipped = 0
    for case in ET.parse(report).getroot().iter("testcase"):
        children = list(case)
        if any(
            child.tag == "skipped"
            or (child.tag in {"failure", "error"} and _is_cluster_skip(child))
            for child in children
        ):
            skipped += 1
        elif any(child.tag in {"failure", "error"} for child in children):
            failed += 1
        else:
            passed += 1
    return passed, failed, skipped


def run_file(root: Path, path: str, ids: list[str], report: Path) -> tuple[int, int, int]:
    """Run selected cluster items for one test file and validate its JUnit report."""
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        "--strict-markers",
        "--rezono-cluster",
        "-m",
        "cluster",
        "-q",
        "-rA",
        "--tb=short",
        "--rootdir",
        str(root),
        f"--junitxml={report}",
        "--",
        *ids,
    ]
    result = subprocess.run(command, cwd=root)
    try:
        ok, bad, skip = parse_outcomes(report)
    except (OSError, ET.ParseError) as exc:
        raise SystemExit(
            f"ERROR pytest exited {result.returncode} for {path} without a readable JUnit report: {exc}"
        ) from exc

    if result.returncode == ExitCode.NO_TESTS_COLLECTED:
        if ok or bad or skip:
            raise SystemExit(
                f"ERROR pytest reported no tests collected for {path} with outcomes ({ok}, {bad}, {skip})"
            )
        return 0, 0, 0
    if result.returncode == ExitCode.OK:
        if bad or skip or not ok:
            raise SystemExit(
                f"ERROR pytest exited 0 for {path} with unexpected outcomes ({ok} passed, {bad} failed, {skip} skipped)"
            )
        return ok, bad, skip
    if result.returncode == ExitCode.TESTS_FAILED:
        if not (bad or skip):
            raise SystemExit(f"ERROR pytest exited 1 for {path} without failures or skips in JUnit report")
        return ok, bad, skip
    if result.returncode == ExitCode.USAGE_ERROR and bad > 0:
        return ok, bad, skip
    raise SystemExit(
        f"ERROR pytest exited {result.returncode} for {path} with outcomes ({ok} passed, {bad} failed, {skip} skipped)"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Repository or fixture root directory")
    parser.add_argument("selection", type=Path, help="Selection file with one pytest node id per line")
    args = parser.parse_args()

    root = args.root.resolve()
    if not root.is_dir():
        raise SystemExit(f"ERROR root directory does not exist: {root}")

    tests = read_selection(args.selection)
    if not tests:
        red_before.summarize("No cluster items in the selection to run on the base.", tests)
        return 0

    files: dict[str, list[str]] = {}
    for test in tests:
        files.setdefault(test.split("::", 1)[0], []).append(test)

    passed = failed = skipped = 0
    with tempfile.TemporaryDirectory() as reports:
        for index, (path, ids) in enumerate(files.items()):
            report = Path(reports) / f"{index}.xml"
            ok, bad, skip = run_file(root, path, ids, report)
            print(f"{path}: {ok} passed, {bad} failed, {skip} skipped", flush=True)
            passed += ok
            failed += bad
            skipped += skip

    if not (passed or failed or skipped):
        red_before.summarize("No cluster items in the selection to run on the base.", tests)
        return 0
    if skipped:
        red_before.summarize(
            f"ERROR {skipped} added cluster test case(s) skipped on the base "
            f"({passed} passed, {failed} failed); a skip proves nothing.",
            tests,
        )
        return 1
    if failed:
        red_before.summarize(
            f"The base source fails {failed} added cluster test case(s) "
            f"({passed} passed, 0 skipped): they tell the base from the change.",
            tests,
        )
        return 0
    red_before.summarize(
        f"ERROR all {passed} added cluster test case(s) pass on the base source "
        "and none fails (0 skipped), so they do not tell the old source from the new one.",
        tests,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
