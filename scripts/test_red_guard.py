"""Regression cases for the policy, using inert bytes without executing proposed changes."""
import ast
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from red_guard import (DEFINITION, UNREADABLE_CONFIG, Change, Tree, allowed, pack_hash, pin_update, protected,
                       review, source)


def main():
    reason = b'pytest.mark.xfail(strict=True, reason="pending")'
    updated = reason.replace(b"pending", b"documented")
    function = b"@" + reason + b"\ndef test_count():\n    assert count() == 2\n"
    cases = [
        ("changed test expectation", "tests/test_count.py", function, function.replace(b"== 2", b"== 3"), False),
        ("changed recorded outcome", "examples/demo/expected/rows.json", b"[2]", b"[3]", False),
        ("changed recorded slip", "examples/platform/slip.yaml", b"sentence: two\n", b"sentence: three\n", False),
        ("changed recorded slip of another example", "examples/subsidy/slip.yaml", b"a\n", b"b\n", False),
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
    read_cases(function)
    pin_cases(function)
    table_cases()
    pytest_config_cases(function)
    green_to_red_cases()


def pytest_config_cases(function):
    """The pytest section of pyproject.toml, setup.cfg or tox.ini can drop a test from the run."""
    lifted = function.split(b"\n", 1)[1]
    project = b'[project]\nname = "demo"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    ignored = project + b'addopts = "--ignore=tests/test_a.py"\n'
    renamed = project.replace(b'"demo"', b'"demo2"')
    cases = [
        ("pytest section of pyproject.toml", "demo/pyproject.toml", project, ignored, True),
        ("other section of pyproject.toml", "demo/pyproject.toml", project, renamed, False),
        ("pytest section added to pyproject.toml", "pyproject.toml", b'[project]\nname = "demo"\n',
         b'[project]\nname = "demo"\n\n[tool.pytest]\naddopts = ["--ignore=tests"]\n', True),
        ("pytest section of setup.cfg", "demo/setup.cfg", b"[metadata]\nname = demo\n\n[tool:pytest]\naddopts = -q\n",
         b"[metadata]\nname = demo\n\n[tool:pytest]\naddopts = -q --ignore=tests\n", True),
        ("other section of setup.cfg", "demo/setup.cfg", b"[metadata]\nname = demo\n", b"[metadata]\nname = demo2\n",
         False),
        ("pytest section of tox.ini", "tox.ini", b"[pytest]\naddopts = -q\n", b"[pytest]\naddopts = -q -k 'not a'\n",
         True),
        ("pyproject.toml that no longer parses", "demo/pyproject.toml", project, project + b"[[[\n", True),
        ("pyproject.toml replaced by a link", "demo/pyproject.toml", project, UNREADABLE_CONFIG, True),
        ("new pyproject.toml as a link", "demo/pyproject.toml", None, UNREADABLE_CONFIG, True),
        ("removed pyproject.toml with a pytest section", "demo/pyproject.toml", project, None, True),
    ]
    for label, path, before, after, expected in cases:
        status = "A" if before is None else "D" if after is None else "M"
        change = Change(path, status, before, after)
        errors, notes = review([change], planner=False)
        if bool(errors) != expected or (f"CHANGED {path} pytest configuration" in notes) != expected:
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        errors, notes = review([change], planner=True)
        if errors:
            raise AssertionError(f"{label} with planner: errors {errors}")
        print(f"{'DENY' if expected else 'ALLOW'} without planner, ALLOW with planner: {label}")
    # Beside a lifted mark, a changed pytest section is another protected change.
    errors, _ = review([Change("tests/test_count.py", "M", function, lifted),
                        Change("demo/pyproject.toml", "M", project, ignored)], planner=True)
    if not any("Lift marks in a pull request of their own" in e for e in errors):
        raise AssertionError(f"lifted mark beside a pytest section: errors {errors}")
    print("DENY with planner: lifted mark beside a changed pytest section")
    # pytest 9 reads these before pyproject.toml, as its whole configuration: an added one that
    # collects only some names hides a red test whose mark goes.
    narrow = b'[pytest]\npython_functions = ["test_k*"]\n'
    for name in ("pytest.toml", ".pytest.toml", ".pytest.ini"):
        path = f"compiler/{name}"
        if not protected(path):
            raise AssertionError(f"{path} is not protected")
        for status, before, after in (("A", None, narrow), ("M", narrow, narrow + b"addopts = '-q'\n"),
                                      ("D", narrow, None)):
            errors, _ = review([Change(path, status, before, after)], planner=False)
            if errors != [f"ERROR planner label required for {ascii(path)}"]:
                raise AssertionError(f"{status} {path} without planner: errors {errors}")
        errors, _ = review([Change("tests/test_count.py", "M", function, lifted),
                            Change(path, "A", None, narrow)], planner=False)
        if not errors:
            raise AssertionError(f"lifted mark beside an added {path} without planner passed")
        errors, _ = review([Change("tests/test_count.py", "M", function, lifted),
                            Change(path, "A", None, narrow)], planner=True)
        if not any("Lift marks in a pull request of their own" in e for e in errors):
            raise AssertionError(f"lifted mark beside an added {path}: errors {errors}")
        print(f"DENY without planner (A, M, D) and beside a lifted mark with planner: {path}")


def green_to_red_cases():
    """A new red mark on a test that was green is reported, and needs the planner label."""
    green = b"import pytest\n\n\ndef test_a():\n    assert f() == 1\n"
    mark = b"@pytest.mark.xfail(strict=True, reason=\"M1: x\")\n"
    other = b"\n\n" + mark + b"def test_b():\n    assert f() == 2\n"
    top = b"import pytest\n\n\n"
    param = (top + b"@pytest.mark.parametrize('v', [1, 2])\ndef test_a(v):\n    assert f(v)\n",
             top + b"@pytest.mark.parametrize('v', [1, pytest.param(2, marks=pytest.mark.xfail("
             b"strict=True, reason=\"M1: x\"))])\ndef test_a(v):\n    assert f(v)\n")
    marked = green.replace(b"def test_a", mark + b"def test_a")
    cases = [
        ("function mark on a green test", green, marked),
        ("same mark as a red test beside it", green + other, marked + other),
        ("module mark over a green test", green,
         green.replace(b"\n\n\ndef", b"\npytestmark = pytest.mark.xfail(strict=True, reason=\"M1: x\")\n\n\ndef")),
        ("parameter mark on a green test", *param),
    ]
    for label, before, after in cases:
        change = Change("tests/test_a.py", "M", before, after)
        note = "CHANGED tests/test_a.py::test_a from green to red"
        errors, notes = review([change], planner=False)
        if note not in notes or not any("turn red" in e for e in errors):
            raise AssertionError(f"{label} without planner: errors {errors}, notes {notes}")
        errors, notes = review([change], planner=True)
        if errors or note not in notes:
            raise AssertionError(f"{label} with planner: errors {errors}, notes {notes}")
        print(f"DENY without planner, ALLOW with planner and reported: {label}")
    errors, notes = review([Change("tests/test_a.py", "M", green + other, green + other.replace(b"M1", b"M2"))],
                           planner=True)
    if any("from green to red" in n for n in notes):
        raise AssertionError(f"a red test that stays red is not green to red: notes {notes}")
    print("ALLOW: a red test that stays red is not reported as green to red")


def table_cases():
    """A case that goes from a parametrize table is REMOVED, at module level or inline."""
    path = "compiler/tests/test_module.py"
    table = (b"import pytest\n\nREFUSALS = {\n    'a check': (1, 'check'),\n    'a reason': (2, 'reason'),\n}\n\n\n"
             b"@pytest.mark.parametrize('name', REFUSALS)\ndef test_refused(name):\n    assert REFUSALS[name]\n")
    shorter = table.replace(b"    'a reason': (2, 'reason'),\n", b"")
    longer = table.replace(b"    'a reason'", b"    'a third': (3, 'third'),\n    'a reason'")
    listed = b"import pytest\n\n\n" + b"@pytest.mark.parametrize('v', [1, 2, 3])\ndef test_v(v):\n    assert v\n"
    marked = table.replace(b"(2, 'reason')", b"pytest.param(2, 'reason', marks=pytest.mark.xfail("
                           b"strict=True, reason='M1: x'))")
    lifted = table.replace(b"(2, 'reason')", b"pytest.param(2, 'reason')")
    cases = [
        ("a case removed from a module-level table", table, shorter,
         [f"CHANGED {path}::test_refused reads the changed REFUSALS", f"REMOVED {path}::test_refused['a reason']"]),
        ("a case added to a module-level table", table, longer,
         [f"CHANGED {path}::test_refused reads the changed REFUSALS"]),
        ("a case removed from an inline parametrize list", listed, listed.replace(b"[1, 2, 3]", b"[1, 3]"),
         [f"CHANGED {path}::test_v", f"REMOVED {path}::test_v[2]"]),
    ]
    for label, before, after, expected in cases:
        change = Change(path, "M", before, after)
        errors, notes = review([change], planner=True)
        if errors or sorted(notes) != sorted(expected):
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        errors, _ = review([change], planner=False)
        if errors != [f"ERROR planner label required for {ascii(path)}"]:
            raise AssertionError(f"{label} without planner: errors {errors}")
        print(f"REPORTED, and DENY without planner: {label}")
    errors, notes = review([Change(path, "M", marked, lifted)], planner=False)
    if errors or notes:
        raise AssertionError(f"a lifted mark in a table: errors {errors}, notes {notes}")
    print("ALLOW without planner, nothing reported: a lifted mark in a module-level table")


def pin_cases(function):
    """With the label, a fixture pack may re-pin an import to the hash the guard computes."""
    source_of = Path(__file__).resolve().parent.parent / "compiler/rezono_compiler/modules.py"
    tree_of = ast.parse(source_of.read_text(encoding="utf-8"))
    compiled = next(ast.literal_eval(node.value) for node in tree_of.body if isinstance(node, ast.Assign)
                    and [getattr(t, "id", None) for t in node.targets] == ["DEFINITION"])
    if compiled != DEFINITION:
        raise AssertionError(f"red_guard.DEFINITION differs from the compiler's: {compiled}")
    print("SAME: the pack definition files of the guard and the compiler")

    lifted = function.split(b"\n", 1)[1]
    lift = Change("tests/test_count.py", "M", function, lifted)
    access, explain = "packs/std-access", "packs/std-explain"
    files = {f"{access}/pack.yaml": b"name: std-access\n", f"{access}/rules/access.dl": b"may_read(r, k).\n",
             f"{access}/expected/out.json": b"[]\n", f"{explain}/pack.yaml": b"name: std-explain\n"}
    # At the base the imported pack's rules differ: its definition changes in the pull request.
    before = dict(files, **{f"{access}/rules/access.dl": b"may_read(r).\n"})
    tree, base = Tree.of(files), Tree.of(before)
    new, old, other = pack_hash(tree, access), pack_hash(base, access), pack_hash(tree, explain)

    def fixture(digest, extra=b""):
        return (b"name: neutral\nimports:\n  - name: std-access\n    path: ../../../packs/std-access\n"
                b"    sha256: " + digest.encode() + b"\n" + extra
                + b"  - name: std-explain\n    path: ../../../packs/std-explain\n"
                b"    sha256: " + other.encode() + b"\n")

    pinned = Change("tests/fixtures/neutral/pack.yaml", "M", fixture(old), fixture(new))
    changed = Change(f"{access}/rules/access.dl", "M", None, None)

    def run(label, changes, expected, planner=True, at=tree, since=base):
        pins = frozenset(c.path for c in changes if pin_update(c, at, since))
        errors, notes = review(changes, planner=planner, pins=pins)
        allowed_ = not errors and "PINNED tests/fixtures/neutral/pack.yaml" in notes
        if allowed_ != expected:
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        print(f"{'ALLOW' if expected else 'DENY'} {'with' if planner else 'without'} planner: {label}")

    run("a pin update to the computed hash beside a lifted mark", [lift, changed, pinned], True)
    run("a pin update to the computed hash, without the label", [lift, changed, pinned], False, planner=False)
    run("a pin update to another hash", [lift, changed, Change(pinned.path, "M", fixture(old), fixture("ab" * 32))],
        False)
    run("a pin update with an added line beside it",
        [lift, changed, Change(pinned.path, "M", fixture(old), fixture(new, b"  # moved\n"))], False)
    run("a pin update whose other lines change too", [lift, changed, Change(
        pinned.path, "M", fixture(old), fixture(new).replace(b"name: neutral", b"name: neutral2"))], False)
    run("a pin update without a change in the imported pack", [lift, pinned], False, since=tree)
    # A stale pin at the base, and a file outside the pack's definition added: the hash does
    # not move in this pull request, so setting the pin right is no pin update.
    noted = dict(files, **{f"{access}/NOTES.txt": b"notes\n"})
    run("a stale pin set right beside a file outside the definition", [
        lift, Change(f"{access}/NOTES.txt", "A", None, None),
        Change(pinned.path, "M", fixture("cc" * 32), fixture(new))], False, at=Tree.of(noted), since=tree)
    run("a new fixture pack.yaml", [lift, changed, Change(pinned.path, "A", None, fixture(new))], False)
    run("a pin update outside a fixture or test directory",
        [lift, changed, Change("examples/demo/expected/pack.yaml", "M", fixture(old), fixture(new))], False)
    # The pinned pack imports the changed one: its hash moves with its own new pin.
    middle = "packs/std-middle"

    def importer(digest):
        return b"name: std-middle\nimports:\n  - name: std-access\n    path: ../std-access\n    sha256: " + digest

    deep = Tree.of(dict(files, **{f"{middle}/pack.yaml": importer(new.encode())}))
    deep_base = Tree.of(dict(before, **{f"{middle}/pack.yaml": importer(old.encode())}))
    via = b"name: neutral\nimports:\n  - name: std-middle\n    path: ../../../packs/std-middle\n    sha256: "
    run("a pin update of a pack that imports the changed pack", [lift, changed, Change(
        pinned.path, "M", via + pack_hash(deep_base, middle).encode() + b"\n",
        via + pack_hash(deep, middle).encode() + b"\n")], True, at=deep, since=deep_base)
    flow = b"imports:\n  - {name: std-access, path: ../../../packs/std-access, sha256: %s}\n"
    run("a pin update in a flow mapping", [lift, changed, Change(
        pinned.path, "M", flow % old.encode(), flow % new.encode())], True)
    anchored = b"imports:\n  - &access {name: std-access, path: ../../../packs/std-access, sha256: %s}\n"
    run("a pin update in a file with an anchor", [lift, changed, Change(
        pinned.path, "M", anchored % old.encode(), anchored % new.encode())], False)
    two = b"---\nname: other\n---\n" + flow
    run("a pin update in a file with a second document", [lift, changed, Change(
        pinned.path, "M", two % old.encode(), two % new.encode())], False)
    linked = Tree(dict(Tree.of(files).modes, **{f"{access}/rules/link.dl": "120000"}), files.__getitem__)
    run("a pin update of a pack that holds a symbolic link", [lift, changed, pinned], False, at=linked)


def workflow_cases():
    """The workflows that define required checks, and what they run to decide, need the label."""
    deciders = (".github/workflows/python-environment/action.yml", "loop/rezono_cluster.py",
                "scripts/cluster_worker_tasks.py", "scripts/role_publication_ci.py",
                "scripts/components.py", "scripts/fast_check.py", "loop/cluster/select_tests.py",
                "scripts/red_list.py")
    for path in deciders:
        # Protected, yet still source: red_before.py runs added tests against the base copy.
        if not (protected(path) and source(path)):
            raise AssertionError(f"{path}: protected {protected(path)}, source {source(path)}")
        print(f"PROTECTED and source: {path}")
    if source("examples/platform/slip.yaml"):
        raise AssertionError("a recorded slip is evidence, not source")
    for path in (".github/workflows/ci.yml", ".github/workflows/disposable-cluster.yml", *deciders):
        for status, after in (("M", b"jobs: {}\n"), ("D", None)):
            change = Change(path, status, b"jobs: {check: {}}\n", after)
            errors, notes = review([change], planner=False)
            if errors != [f"ERROR planner label required for {ascii(path)}"]:
                raise AssertionError(f"{status} {path} without planner: errors {errors}")
            errors, notes = review([change], planner=True)
            if errors or (path.endswith("ci.yml") and f"CHANGED {path}" not in notes):
                raise AssertionError(f"{status} {path} with planner: errors {errors}, notes {notes}")
            print(f"DENY without planner, ALLOW with planner: {status} {path}")


def read_cases(function):
    """A change to the checker or read access needs the read label for its head commit."""
    head = "0123456789abcdef" * 2 + "01234567"
    current, stale = "p1-read-" + head, "p1-read-" + "fedcba98" * 5
    prefix = "p1-read-" + head[:7]
    # Another commit that shares the first seven characters must not inherit the label.
    twin = head[:7] + "f" * 33
    checker = [Change("checker/rezono_checker/proof.py", "M", None, None)]
    lifted = function.split(b"\n", 1)[1]

    def run(label, changes, labels, expected, planner=True, at=head):
        errors, _ = review(changes, planner=planner, head=at, labels=labels)
        refused = [e for e in errors if "p1-read-" in e]
        if bool(refused) != expected or (not expected and errors):
            raise AssertionError(f"{label}: errors {errors}")
        print(f"{'DENY' if errors else 'ALLOW'}: {label}")

    run("checker change without a label", checker, [], True, planner=False)
    run("checker change with only the planner label", checker, ["planner"], True)
    run("checker change labelled for an earlier commit", checker, ["planner", stale], True)
    run("checker change labelled for its head commit", checker, ["planner", current], False)
    run("checker change with a read label but a malformed head", checker, [current], True, at=head[:7])
    run("checker change labelled with only the prefix of its head", checker, ["planner", prefix], True)
    run("checker change at another commit with the same prefix", checker, ["planner", current], True,
        at=twin)
    canon = [Change("canon/rezono_canon/__init__.py", "M", None, None)]
    run("canonical encoding change without a label", canon, ["planner"], True)
    run("canonical encoding change labelled for its head commit", canon, ["planner", current], False)
    run("only marks lifted in tests under the read paths", [
        Change("checker/rezono_checker/tests/test_proof.py", "M", function, lifted),
        Change("packs/std-access/tests/test_access.py", "M", function, lifted),
    ], [], False, planner=False)
    run("only tests changed under the read paths", [
        Change("edge/gate/src/ask.test.ts", "M", b"a", b"b"),
        Change("checker/rezono_checker/conftest.py", "M", b"a = 1\n", b"a = 2\n"),
    ], ["planner"], False)
    for path in ("checker/rezono_checker/proof.py", "packs/std-access/rules/access.dl",
                 "edge/gate/src/ask.ts", "edge/publisher/rezono_publisher/access.py",
                 "contracts/proof.yaml", "checker/rezono_checker/fixtures.py",
                 *(f"edge/publisher/rezono_publisher/{name}.py" for name in (
                     "calc_scope", "sources", "sweep", "difference", "batch", "publish", "proof", "views",
                     "retained_calculation"))):
        for status in ("M", "A", "D"):
            run(f"{status} {path} without a read label", [Change(path, status, None, None)],
                ["planner"], True)
    sweep = [Change("edge/publisher/rezono_publisher/sweep.py", "M", None, None)]
    run("sweep change in the publisher with only the planner label", sweep, ["planner"], True)
    run("sweep change in the publisher labelled for its head commit", sweep, ["planner", current], False)
    run("other publisher change without a read label",
        [Change("edge/publisher/rezono_publisher/store.py", "M", None, None)], [], False, planner=False)
    run("other contracts change without a read label",
        [Change("contracts/facts.yaml", "M", None, None)], [], False, planner=False)
    errors, _ = review(checker, planner=True)
    if errors:
        raise AssertionError(f"the merge queue reads no labels: errors {errors}")
    print("ALLOW in the merge queue: checker change without labels")


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
    run("lifted mark beside a changed recorded outcome and a test helper", [
        edit("tests/test_count.py", function, lifted),
        edit("examples/demo/expected/rows.json", b"[2]", b"[3]"),
        edit("tests/support.py", b"value = 2\n", b"value = 3\n"),
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
    run("changed recorded slip", [edit("examples/platform/slip.yaml", b"sentence: two\n", b"sentence: three\n")],
        False, ["CHANGED examples/platform/slip.yaml"])
    run("weakened expectation without a source change", [
        edit("compiler/tests/test_total.py", other, other.replace(b"== 4", b"is not None")),
    ], False, ["CHANGED compiler/tests/test_total.py::test_total"])
    errors, notes = review([edit("tests/test_count.py", pair, lifted + b"\n" + other),
                            edit("src/count.py", b"", b"")], planner=False)
    if errors or any(n.startswith("CHANGED tests/") for n in notes):
        raise AssertionError(f"a lifted mark is not a change: errors {errors}, notes {notes}")
    print("ALLOW without planner: lifted mark is not reported as a change")
    milestone_cases(edit, other)
    completion_cases(edit, function, lifted, other, reason)


def completion_cases(edit, function, lifted, other, reason):
    """With the label, one lifted mark may come with new evidence data its test reads."""
    outcome = Change("examples/demo/expected/rows.json", "A", None, b"[3]")
    case = Change("examples/demo/snapshots/count.json", "A", None, b"{\"count\": 2}\n")
    lift = edit("tests/test_count.py", function, lifted)
    refusal = "Lift marks in a pull request of their own"
    # The pack roots of the reviewed revision: the directories with a pack.yaml.
    roots = frozenset({"examples/demo", "packs/demo"})

    def run(label, changes, planner, expected, packs=roots, test="tests/test_count.py"):
        errors, notes = review(changes, planner=planner, packs=packs)
        refused = any(refusal in e for e in errors)
        completed = f"COMPLETED {test}::test_count" in notes
        if refused != expected or completed == expected or (not expected and errors):
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        print(f"{'DENY' if expected else 'ALLOW'} {'with' if planner else 'without'} planner: {label}")

    run("one lifted mark beside evidence data only", [lift, outcome, case], True, False)
    # A reviewer reads where the evidence came from before it lands: the read label for the head.
    head = "0123456789abcdef" * 2 + "01234567"
    for labels, expected in ((["planner"], True), (["planner", "p1-read-" + head[:7]], True),
                             (["planner", "p1-read-" + head], False)):
        errors, notes = review([lift, outcome, case], planner=True, head=head, labels=labels, packs=roots)
        refused = any("p1-read-" + head in e and "completes" in e for e in errors)
        if refused != expected or "COMPLETED tests/test_count.py::test_count" not in notes:
            raise AssertionError(f"evidence completion with {labels}: errors {errors}, notes {notes}")
        print(f"{'DENY' if expected else 'ALLOW'} with {labels}: an evidence completion needs the read label")
    run("one lifted mark beside evidence data, without the label", [lift, outcome], False, True)
    run("one lifted mark beside evidence data and another protected path",
        [lift, outcome, edit("tests/support.py", b"value = 2\n", b"value = 3\n")], True, True)
    marked = b"@pytest.mark.xfail(strict=True, reason=\"M2: pending\")\n" + other
    run("one lifted mark beside evidence data and a mark of another test",
        [lift, outcome, edit("tests/test_total.py", marked, other)], True, True)
    pair = function + b"\n" + marked
    run("one lifted mark beside evidence data and an explained mark of another test",
        [edit("tests/test_count.py", pair, lifted + b"\n" + marked.replace(b"pending", b"waiting")), outcome],
        True, True)
    run("one lifted mark beside evidence data and source",
        [lift, outcome, edit("src/count.py", b"", b"x = 1\n")], True, True)
    run("one lifted mark beside removed evidence data",
        [lift, Change("examples/demo/expected/rows.json", "D", b"[2]", None)], True, True)
    run("one lifted mark beside a changed policy workflow",
        [lift, outcome, edit(".github/workflows/ci.yml", b"a", b"b")], True, True)
    run("one lifted mark beside a changed conftest",
        [lift, edit("tests/conftest.py", b"value = 2\n", b"value = 3\n")], True, True)
    # A changed outcome could weaken what the test already expects; only added files count.
    run("one lifted mark beside changed evidence data",
        [lift, edit("examples/demo/expected/rows.json", b"[2]", b"[3]")], True, True)
    # Data outside expected/, snapshots/ and vectors/ configures what runs or is accepted.
    for path in ("blocked/tests.txt", "tests/fixtures/rows.json", "tests/conformance/count.yaml",
                 "examples/demo/expected/rows.schema.json", "examples/demo/expected/pack.yaml",
                 "rezono/test/expected/not-yet.json", "contracts/expected/proof.json",
                 "examples/demo/expected/fixtures/rows.json", "examples/demo/expected/rows.py"):
        run(f"one lifted mark beside {path}",
            [lift, outcome, Change(path, "A", None, b"tests/test_count.py\n")], True, True)
    # Without readable bytes, Git recorded no regular file: a symbolic link or an executable.
    run("one lifted mark beside an added symbolic link",
        [lift, Change("examples/demo/expected/rows.json", "A", None, None)], True, True)
    # pytest collects no test in a class whose name does not start with Test.
    hidden = b"class Helper:\n    @" + reason + b"\n    def test_count(self):\n        assert count() == 2\n"
    bare = b"class Helper:\n    def test_count(self):\n        assert count() == 2\n"
    run("one lifted mark on a test that pytest does not collect",
        [edit("tests/test_count.py", hidden, bare), outcome], True, True)
    # The evidence directory sits directly in a pack root, a tests/ or test/ directory, or a
    # directory on the path of the test file.
    run("one lifted mark beside evidence in a tests directory",
        [lift, Change("tests/expected/rows.json", "A", None, b"[3]")], True, False, packs=frozenset())
    run("one lifted mark beside evidence on the path of its test file",
        [edit("suite/checks/test_count.py", function, lifted), Change("suite/expected/rows.json", "A", None, b"[3]")],
        True, False, packs=frozenset(), test="suite/checks/test_count.py")
    run("one lifted mark beside evidence in a directory without pack.yaml",
        [lift, outcome], True, True, packs=frozenset())
    # The compiler reads these directories of a pack as its definition, so the pack would change.
    for path in ("examples/demo/schema/expected/smokkel.yaml", "examples/demo/schema/kinds/expected/a.yaml",
                 "examples/demo/rezono/expected/rows.json", "examples/demo/rules/expected/rows.yaml",
                 "examples/demo/facts/expected/rows.yaml", "examples/demo/labels/expected/rows.yaml",
                 "examples/demo/messages/expected/rows.json", "examples/demo/calc/expected/rows.yaml",
                 "packs/demo/expected/rows.json", "examples/other/expected/rows.json",
                 "examples/demo/notes/expected/rows.json"):
        run(f"one lifted mark beside {path}", [lift, Change(path, "A", None, b"kind: smuggled\n")], True, True)


def milestone_cases(edit, other):
    """A red mark says which milestone it serves, in literal text, and keeps one.

    Only the planner label moves a mark to a later milestone.
    """
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
            ("reason moves to a later milestone", red(b'"M3: pending"'), not planner),
            ("reason moves to later: ", red(b'"later: pending"'), not planner),
        ):
            run(label, [edit("tests/test_total.py", marked, after)], expected, planner)
    pair = red(b'"M2: pending"') + b"\n" + red(b'"later: views"').replace(b"test_total", b"test_sum")
    run("two tests trade milestones", [
        edit("tests/test_total.py", pair, pair.replace(b"M2: ", b"M3: ", 1).replace(b"later: views", b"M2: views")),
    ], True, planner=False)
    two = red(b'"M1: pending"').replace(b"def test_total():",
                                        b"@pytest.mark.xfail(strict=True, reason=\"M2: other\")\ndef test_total():")
    run("one of two marks on a test lifted, the other postponed", [
        edit("tests/test_total.py", two, red(b'"later: pending"')),
    ], True, planner=False)
    run("one of two marks on a test lifted, the other kept", [
        edit("tests/test_total.py", two, red(b'"M1: pending"')),
    ], False, planner=False)
    run("reason without a milestone gets one", [
        edit("tests/test_total.py", red(b'"pending"'), red(b'"later: pending"')),
    ], False, planner=False)
    run("reason without a milestone is explained",
        [edit("tests/test_total.py", red(b'"pending"'), red(b'"documented"'))], False, planner=False)


if __name__ == "__main__":
    main()
