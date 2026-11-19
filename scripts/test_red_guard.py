"""Regression cases for the policy, using inert bytes without executing proposed changes."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from red_guard import Change, allowed, review


def main():
    reason = b'pytest.mark.xfail(strict=True, reason="pending")'
    updated = reason.replace(b"pending", b"documented")
    function = b"@" + reason + b"\ndef test_count():\n    assert count() == 2\n"
    cases = [
        ("changed test expectation", "tests/test_count.py", function, function.replace(b"== 2", b"== 3"), False),
        ("changed recorded outcome", "examples/demo/expected/rows.json", b"[2]", b"[3]", False),
        ("removed policy workflow", ".github/workflows/red-policy.yml", b"policy", None, False),
        ("changed policy implementation", "scripts/red_guard.py", b"review", b"other", False),
        ("changed shared fixture", "contracts/fixtures/data.json", b"{}", b"[]", False),
        ("changed test helper", "tests/support.py", b"value = 2\n", b"value = 3\n", False),
        ("changed test setup", "demo/conftest.py", b"value = 2\n", b"value = 3\n", False),
        ("removed function mark", "tests/test_count.py", function, function.split(b"\n", 1)[1], True),
        ("explained function mark", "tests/test_count.py", function, function.replace(reason, updated), True),
    ]
    cls = b"@" + reason + b"\nclass TestCount:\n    pass\n"
    module = b"pytestmark = " + reason + b"\n" + b"def test_count(): pass\n"
    for name, source in (("class", cls), ("module", module)):
        cases.extend([
            (f"explained {name} mark", "demo/test_counts.py", source, source.replace(reason, updated), True),
            (f"removed {name} mark", "demo/test_counts.py", source, source.split(b"\n", 1)[1], True),
            (f"added {name} mark", "demo/test_counts.py", source.split(b"\n", 1)[1], source, False),
        ])
    param = b"values = [pytest.param(True, marks=" + reason + b")]\n"
    cases.append(("removed parameter mark", "demo/test_counts.py", param, b"values = [pytest.param(True)]\n", True))
    for label, path, before, after, expected in cases:
        actual = allowed(path, before, after)
        if actual != expected:
            raise AssertionError(f"{label}: expected {expected}, got {actual}")
        print(f"{'ALLOW' if actual else 'DENY'} without planner: {label}")
    planner_cases(reason, function)
    workflow_cases()


def workflow_cases():
    """The workflows that define required checks need the planner label to change."""
    for path in (".github/workflows/ci.yml", ".github/workflows/disposable-cluster.yml"):
        for status, after in (("M", b"jobs: {}\n"), ("D", None)):
            change = Change(path, status, b"jobs: {check: {}}\n", after)
            errors, notes = review([change], planner=False)
            if errors != [f"ERROR planner label required for {ascii(path)}"]:
                raise AssertionError(f"{status} {path} without planner: errors {errors}")
            errors, notes = review([change], planner=True)
            if errors or (path.endswith("ci.yml") and f"CHANGED {path}" not in notes):
                raise AssertionError(f"{status} {path} with planner: errors {errors}, notes {notes}")
            print(f"DENY without planner, ALLOW with planner: {status} {path}")


def planner_cases(reason, function):
    """The planner label allows protected changes; the guard still runs."""
    lifted = function.split(b"\n", 1)[1]
    other = b"def test_total():\n    assert total() == 4\n"
    # These marks carry a milestone, so that only strictness can refuse them.
    loose = b"@pytest.mark.xfail(reason=\"M2: pending\")\n" + other
    unrun = b"@pytest.mark.xfail(strict=True, run=False, reason=\"M2: pending\")\n" + other
    marked = b"@" + reason.replace(b"pending", b"M2: pending") + b"\n" + other
    milestone = function.replace(b"pending", b"M2: pending")
    pair = function + b"\n" + other

    def run(label, changes, expected, notes=(), cause=None):
        errors, actual_notes = review(changes, planner=True)
        if (bool(errors) != expected or any(n not in actual_notes for n in notes)
                or (cause and not all(cause in e for e in errors))):
            raise AssertionError(f"{label}: errors {errors}, notes {actual_notes}")
        print(f"{'DENY' if errors else 'ALLOW'} with planner: {label}")

    edit = lambda path, before, after: Change(path, "M", before, after)
    run("lifted mark beside a changed expectation", [
        edit("tests/test_count.py", function, lifted),
        edit("tests/test_total.py", other, other.replace(b"== 4", b"== 5")),
    ], True)
    run("lifted mark and changed expectation in one file", [
        edit("tests/test_count.py", function, lifted.replace(b"== 2", b"== 3")),
    ], True)
    run("lifted mark beside a changed recorded outcome", [
        edit("tests/test_count.py", function, lifted),
        edit("examples/demo/expected/rows.json", b"[2]", b"[3]"),
    ], True)
    run("lifted mark alone", [edit("tests/test_count.py", function, lifted)], False)
    strictly = "needs strict=True"
    run("new mark without strict=True", [edit("tests/test_total.py", other, loose)], True, cause=strictly)
    run("new mark with run=False", [edit("tests/test_total.py", other, unrun)], True, cause=strictly)
    run("strict mark loosened", [edit("tests/test_count.py", milestone, milestone.replace(b"strict=True, ", b""))],
        True, cause=strictly)
    run("new test file with a loose mark", [Change("tests/test_new.py", "A", None, loose)], True, cause=strictly)
    run("new strict mark with a new expectation", [
        edit("tests/test_total.py", other, marked.replace(b"== 4", b"== 5")),
    ], False)
    run("changed expectation without marks", [
        edit("tests/test_total.py", other, other.replace(b"== 4", b"== 5")),
    ], False)
    run("removed test function", [edit("tests/test_count.py", pair, other)], False,
        ["REMOVED tests/test_count.py::test_count"])
    run("removed red test is not a lift", [
        edit("tests/test_count.py", pair, other),
        edit("tests/test_total.py", other, other.replace(b"== 4", b"== 5")),
    ], False, ["REMOVED tests/test_count.py::test_count"])
    run("removed and changed evidence", [
        Change("tests/test_old.py", "D", other, None),
        edit("examples/demo/expected/rows.json", b"[2]", b"[3]"),
        edit("src/count.py", b"", b""),
        edit("tests/test_total.py", other, other.replace(b"== 4", b"== 5")),
        edit(".github/workflows/ci.yml", b"", b""),
    ], False, ["REMOVED tests/test_old.py", "CHANGED examples/demo/expected/rows.json",
               "CHANGED tests/test_total.py::test_total", "CHANGED .github/workflows/ci.yml"])
    run("weakened expectation without a source change", [
        edit("compiler/tests/test_total.py", other, other.replace(b"== 4", b"is not None")),
    ], False, ["CHANGED compiler/tests/test_total.py::test_total"])
    errors, notes = review([edit("tests/test_count.py", pair, lifted + b"\n" + other),
                            edit("src/count.py", b"", b"")], planner=False)
    if errors or any(n.startswith("CHANGED tests/") for n in notes):
        raise AssertionError(f"a lifted mark is not a change: errors {errors}, notes {notes}")
    print("ALLOW without planner: lifted mark is not reported as a change")
    milestone_cases(edit, other)


def milestone_cases(edit, other):
    """A red mark says which milestone it serves, in literal text, and keeps it."""
    def red(reason):
        return b"@pytest.mark.xfail(strict=True, reason=" + reason + b")\n" + other

    def run(label, changes, expected, planner=True):
        errors, _ = review(changes, planner=planner)
        refused = [e for e in errors if "milestone" in e]
        if bool(refused) != expected or (not expected and errors):
            raise AssertionError(f"{label}: errors {errors}")
        print(f"{'DENY' if errors else 'ALLOW'} {'with' if planner else 'without'} planner: {label}")

    computed = b'NOTE = "M2: pending"\n' + red(b"NOTE")
    run("new red test without a milestone", [edit("tests/test_total.py", other, red(b'"pending"'))], True)
    run("new red test with M2: ", [edit("tests/test_total.py", other, red(b'"M2: pending"'))], False)
    run("new red test file without a milestone", [Change("tests/test_new.py", "A", None, red(b'"pending"'))], True)
    run("new red test file with later: ", [Change("tests/test_new.py", "A", None, red(b'"later: views"'))], False)
    run("new red test with a computed reason", [edit("tests/test_total.py", other, computed)], True)
    run("new red test with a formatted reason", [edit("tests/test_total.py", other, red(b'f"M2: {1}"'))], True)
    run("milestone inside the reason", [edit("tests/test_total.py", other, red(b'"see M2: pending"'))], True)
    run("new parameter mark without a milestone", [
        edit("tests/test_total.py", b"values = [pytest.param(1)]\n",
             b'values = [pytest.param(1, marks=pytest.mark.xfail(strict=True, reason="pending"))]\n'),
    ], True)
    marked = red(b'"M2: pending"')
    for planner in (False, True):
        for label, after, expected in (
            ("reason loses its milestone", red(b'"pending"'), True),
            ("reason loses its milestone to a computed value", computed, True),
            ("reason extends the text after its milestone", red(b'"M2: pending on the loader"'), False),
            ("reason moves to an earlier milestone", red(b'"M1: pending"'), False),
        ):
            run(label, [edit("tests/test_total.py", marked, after)], expected, planner)
    run("reason without a milestone is explained",
        [edit("tests/test_total.py", red(b'"pending"'), red(b'"documented"'))], False, planner=False)


if __name__ == "__main__":
    main()
