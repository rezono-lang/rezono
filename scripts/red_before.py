"""Decide whether the tests a pull request adds tell the base source from the new one.

A pull request is mixed when it changes source and adds at least one pytest test
function without a red mark. Source and red marks are defined by `red_guard.py`.
For a mixed pull request, `prepare` checks out the base and lays the pull request's
protected paths over it, and `run` executes only the added tests without a red mark.
If every one of them passes there, they do not distinguish the old source from the
new one, and `run` fails. A test that cannot be loaded on the base does not pass.
`run` reads each test's outcome from a JUnit report, not from the exit code alone:
a skipped or deselected test proves nothing, so `run` fails only when at least one
added test really passes on the base and none fails. When none of them runs there,
it says so and succeeds.

From the repository root:
  python -I scripts/red_before.py discover BASE HEAD
  python -I scripts/red_before.py prepare BASE HEAD SELECTION
  python -I scripts/red_before.py run SELECTION
"""
import argparse
import importlib.util
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

# Read the guard beside this file, which in CI is the base copy of both.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from red_guard import EMPTY, UNREADABLE, changes, git, inventory, protected, source


def pytest_file(path):
    name = PurePosixPath(path).name
    return (name.startswith("test_") and name.endswith(".py")) or name.endswith("_test.py")


def collectable(name):
    """A qualified name that pytest collects by default: test functions in Test classes."""
    *classes, function = name.split("::")
    return function.startswith("test") and all(c.startswith("Test") for c in classes)


def added_tests(records):
    """Node IDs of the test functions that the changes add without a red mark."""
    found = []
    for c in records:
        if not (protected(c.path) and pytest_file(c.path)) or c.after is None:
            continue
        try:
            new = inventory(c.after)
        except UNREADABLE:
            continue  # A test file that does not parse fails the pull request's own check.
        try:
            old = EMPTY if c.before is None else inventory(c.before)
        except UNREADABLE:
            old = EMPTY
        found.extend(f"{c.path}::{name}" for name, (_, red) in new.tests.items()
                     if not red and name not in old.tests and collectable(name))
    return found


def decide(base, head):
    """Return (records, edited source paths, added tests); mixed when both are non-empty."""
    start = git("merge-base", base, head).decode().strip()
    records = list(changes(start, head))
    edited = sorted(c.path for c in records if source(c.path))
    tests = added_tests(records) if edited else []
    return records, edited, tests


def report(edited, tests):
    print(f"{len(edited)} source path(s) changed; {len(tests)} test(s) added without a red mark.",
          file=sys.stderr)
    for path in edited:
        print(f"SOURCE {path}", file=sys.stderr)
    for test in tests:
        print(f"ADDED {test}", file=sys.stderr)


def discover(base, head):
    _, edited, tests = decide(base, head)
    report(edited, tests)
    print(f"required={'true' if edited and tests else 'false'}")
    return 0


def pathspecs(*args, paths):
    if paths:
        subprocess.run(["git", "--literal-pathspecs", *args, "--pathspec-from-file=-", "--pathspec-file-nul"],
                       input="\0".join(paths).encode("utf-8", "surrogateescape"), check=True)


def prepare(base, head, selection):
    records, edited, tests = decide(base, head)
    report(edited, tests)
    if any("\n" in test for test in tests):
        raise ValueError("a test path contains a line break")
    with open(selection, "w", encoding="utf-8") as out:
        out.writelines(f"{test}\n" for test in tests)
    if not (edited and tests):
        print("Not a mixed pull request: nothing runs on the base.")
        return 0
    if git("status", "--porcelain", "--untracked-files=no").strip():
        raise SystemExit("ERROR the working tree has local changes")
    git("checkout", "-q", "--detach", base)
    kept = [c.path for c in records if protected(c.path) and c.status != "D"]
    gone = [c.path for c in records if protected(c.path) and c.status == "D"]
    pathspecs("checkout", head, paths=kept)
    pathspecs("rm", "-q", "--ignore-unmatch", paths=gone)
    print(f"Checked out the base {base} with {len(kept) + len(gone)} protected path(s) from {head}.")
    return 0


def outcomes(report):
    """Count (passed, failed, skipped) test cases in a pytest JUnit XML report."""
    counts = [0, 0, 0]
    for case in ET.parse(report).getroot().iter("testcase"):
        tags = {child.tag for child in case}
        if tags & {"failure", "error"}:
            counts[1] += 1
        elif "skipped" in tags:
            counts[2] += 1
        else:
            counts[0] += 1
    return tuple(counts)


def run(selection):
    with open(selection, encoding="utf-8") as lines:
        tests = [line.rstrip("\n") for line in lines if line.strip()]
    if not tests:
        print("No added tests to run on the base.")
        return 0
    if importlib.util.find_spec("pytest") is None:
        raise SystemExit("ERROR pytest is not installed for this interpreter")
    root = git("rev-parse", "--show-toplevel").decode().strip()
    files = {}
    for test in tests:
        files.setdefault(test.split("::", 1)[0], []).append(test)
    failed = []
    passed = skipped = 0
    with tempfile.TemporaryDirectory() as reports:
        for number, (path, ids) in enumerate(files.items()):
            report = Path(reports) / f"{number}.xml"
            print(f"::group::pytest {path} on the base", flush=True)
            code = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "-rA",
                                   "--tb=short", "--rootdir", root, f"--junitxml={report}", "--", *ids],
                                  cwd=root).returncode
            print("::endgroup::", flush=True)
            try:
                ok, bad, skip = outcomes(report)
            except (OSError, ET.ParseError):
                if not code:
                    raise SystemExit(f"ERROR pytest exited 0 for {path} without a readable JUnit report")
                ok, bad, skip = 0, 0, 0
            print(f"{path}: pytest exit {code} on the base; {ok} passed, {bad} failed, {skip} skipped",
                  flush=True)
            # Exit 5 means nothing was collected: not run, so not a failure. Any other
            # non-zero exit, such as a test that cannot be loaded, does not pass.
            if bad or code not in (0, 5):
                failed.append(path)
            passed += ok
            skipped += skip
    if failed:
        verdict = (f"The base source fails the added tests in {', '.join(failed)}: "
                   "they tell the base from the change.")
        status = 0
    elif passed:
        verdict = (f"ERROR {passed} of the added test case(s) without a red mark pass on the base source "
                   f"and none fails ({skipped} skipped), so they do not tell the old source from the new one. "
                   "Strengthen at least one until it fails on the base. Tests that do not depend on the "
                   "source change go first, in a pull request of their own.")
        status = 1
    else:
        verdict = (f"None of the {len(tests)} added test(s) without a red mark ran on the base source "
                   f"({skipped} skipped, the rest not selected), so this check proves nothing about them.")
        print(f"::warning::{verdict}")
        status = 0
    print(verdict)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as out:
            out.write(f"{verdict}\n\n" + "".join(f"- `{test}`\n" for test in tests))
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)
    for name in ("discover", "prepare"):
        cmd = sub.add_parser(name)
        cmd.add_argument("base")
        cmd.add_argument("head")
        if name == "prepare":
            cmd.add_argument("selection")
    sub.add_parser("run").add_argument("selection")
    args = parser.parse_args()
    if args.cmd == "discover":
        return discover(args.base, args.head)
    if args.cmd == "prepare":
        return prepare(args.base, args.head, args.selection)
    return run(args.selection)


if __name__ == "__main__":
    sys.exit(main())
