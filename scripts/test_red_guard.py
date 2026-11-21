"""Regression cases for the policy, using inert bytes without executing proposed changes."""
import ast
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from red_guard import (DEFINITION, RED_DECISION_BUDGET, UNREADABLE_CONFIG, Change, Tree, allowed,
                       decision_citation, has_valid_decision_head, inventory, pack_hash, pin_update, protected,
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
    table_form_cases()
    plugin_cases(function)
    pytest_config_cases(function)
    green_to_red_cases()
    decision_citation_cases()


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


def table_form_cases():
    """Each way to give or build a parametrize table reports the case it loses."""
    path = "x/tests/test_t.py"
    top = b"import pytest\n\n"
    forms = [
        ("argvalues as a keyword",
         top + b"@pytest.mark.parametrize(argnames='x', argvalues=[1, 2])\ndef test_a(x):\n    assert x\n",
         b"[1, 2]", b"[1]", "test_a", "2", False),
        ("parametrize on a test class",
         top + b"@pytest.mark.parametrize('x', [1, 2])\nclass TestA:\n    def test_a(self, x):\n        assert x\n",
         b"[1, 2]", b"[1]", "TestA::test_a", "2", False),
        ("a module pytestmark",
         top + b"pytestmark = pytest.mark.parametrize('x', [1, 2])\n\n\ndef test_a(x):\n    assert x\n",
         b"[1, 2]", b"[1]", "test_a", "2", False),
        ("a table derived from another",
         top + b"BASE = [1, 2]\nCASES = BASE + [3]\n\n\n\x40pytest.mark.parametrize('x', CASES)\ndef test_a(x):\n"
         b"    assert x\n", b"BASE = [1, 2]", b"BASE = [1]", "test_a", "2", "CASES"),
        ("a module-level += that goes",
         top + b"CASES = [1]\nCASES += [2]\n\n\n\x40pytest.mark.parametrize('x', CASES)\ndef test_a(x):\n"
         b"    assert x\n",
         b"CASES += [2]\n", b"", "test_a", "2", "CASES"),
        ("a module-level append that goes",
         top + b"CASES = [1]\nCASES.append(2)\n\n\n\x40pytest.mark.parametrize('x', CASES)\ndef test_a(x):\n"
         b"    assert x\n", b"CASES.append(2)\n", b"", "test_a", "2", "CASES"),
        ("a table read through .values()",
         top + b"T = {'a': 1, 'b': 2}\n\n\n\x40pytest.mark.parametrize('x', T.values(), ids=T)\ndef test_a(x):\n"
         b"    assert x\n", b"'b': 2", b"'c': 3", "test_a", "'b'", "T"),
    ]
    for label, before, old, new, test, case, name in forms:
        after = before.replace(old, new, 1)
        errors, notes = review([Change(path, "M", before, after)], planner=True)
        if errors or f"REMOVED {path}::{test}[{case}]" not in notes or (
                name and f"CHANGED {path}::{test} reads the changed {name}" not in notes):
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        print(f"REPORTED: a case lost through {label}")
    # A helper that returns the table: the test reads it, so it reads the change.
    helper = (top + b"T = {'a': 1, 'b': 2}\n\n\ndef rows():\n    return T\n\n\ndef test_a():\n"
              b"    assert rows()\n")
    errors, notes = review([Change(path, "M", helper, helper.replace(b", 'b': 2", b""))], planner=True)
    if errors or f"CHANGED {path}::test_a reads the changed rows" not in notes:
        raise AssertionError(f"a helper that returns a table: errors {errors}, notes {notes}")
    print("REPORTED: a test that calls a helper whose table changes")
    # A fixture's params parametrize every test that takes it, directly or through another fixture.
    fixture = (top + b"\x40pytest.fixture(params=['a', 'b'])\ndef letter(request):\n    return request.param\n\n\n"
               b"\x40pytest.fixture\ndef word(letter):\n    return letter * 2\n\n\n"
               b"def test_letter(letter):\n    assert letter\n\n\ndef test_word(word):\n    assert word\n")
    errors, notes = review([Change(path, "M", fixture, fixture.replace(b"['a', 'b']", b"['a']"))], planner=True)
    for test, name in (("test_letter", "letter"), ("test_word", "word")):
        if (errors or f"REMOVED {path}::{test}['b']" not in notes
                or f"CHANGED {path}::{test} reads the changed {name}" not in notes):
            raise AssertionError(f"a case lost from fixture params: errors {errors}, notes {notes}")
    print("REPORTED: a case lost from the params of a fixture a test takes, directly or not")
    at = b"\x40pytest."
    params = at + b"fixture(params=['a', 'b']"
    forms = [
        ("a fixture named with name=", top + params + b", name='letter')\ndef make_letter(request):\n"
         b"    return request.param\n\n\ndef test_a(letter):\n    assert letter\n", "test_a"),
        ("a fixture named in usefixtures", top + params + b")\ndef letter(request):\n    return request.param\n\n\n"
         + at + b"mark.usefixtures('letter')\ndef test_a():\n    assert True\n", "test_a"),
        ("an autouse fixture", top + params + b", autouse=True)\ndef letter(request):\n    return request.param\n\n\n"
         b"def test_a():\n    assert True\n", "test_a"),
        ("a fixture defined in the test class", top + b"class TestA:\n    " + params
         + b")\n    def letter(self, request):\n        return request.param\n\n"
         b"    def test_a(self, letter):\n        assert letter\n", "TestA::test_a"),
        ("pytest_generate_tests", top + b"def pytest_generate_tests(metafunc):\n"
         b"    metafunc.parametrize('letter', ['a', 'b'])\n\n\ndef test_a(letter):\n    assert letter\n", "test_a"),
    ]
    for label, before, test in forms:
        after = before.replace(b"['a', 'b']", b"['a']")
        errors, notes = review([Change(path, "M", before, after)], planner=True)
        if errors or f"REMOVED {path}::{test}['b']" not in notes or not any(
                n.startswith(f"CHANGED {path}::{test} ") for n in notes):
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        print(f"REPORTED: a case lost through {label}")
    deleted = top + b"T = {'a': 1, 'b': 2}\n\n\n\x40pytest.mark.parametrize('x', T)\ndef test_a(x):\n    assert x\n"
    errors, notes = review([Change(path, "M", deleted, deleted.replace(b"\n\n\n@", b"\ndel T['b']\n\n\n@"))],
                           planner=True)
    if f"REMOVED {path}::test_a['b']" not in notes:
        raise AssertionError(f"a module-level del: errors {errors}, notes {notes}")
    print("REPORTED: a case lost through a module-level del")
    # Any other module-level change to a table, however it is written, reports the tests.
    base = top + b"CASES = [1, 2]\n\n\n\x40pytest.mark.parametrize('x', CASES)\ndef test_a(x):\n    assert x\n"
    under = f"CHANGED {path}::test_a under a changed module-level statement"
    reads = f"CHANGED {path}::test_a reads the changed CASES"
    for label, line, expected in (
            ("CASES.remove(2)", b"CASES.remove(2)\n", [reads, f"REMOVED {path}::test_a[2]"]),
            ("CASES.pop()", b"CASES.pop()\n", [reads]),
            ("an if that rebinds CASES", b"if True:\n    CASES = [1]\n", [reads]),
            ("a for loop that removes from CASES", b"for _c in [2]:\n    CASES.remove(_c)\n", [reads]),
            ("globals() that rebinds CASES", b"globals()['CASES'] = [1]\n", [under]),
            ("exec at module level", b"exec('CASES = [1]')\n", [under])):
        after = base.replace(b"\n\n\n\x40", b"\n" + line + b"\n\n\x40")
        errors, notes = review([Change(path, "M", base, after)], planner=True)
        if errors or any(note not in notes for note in expected):
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        print(f"REPORTED: a module-level {label}")


def plugin_cases(function):
    """A package that registers a pytest plugin can drop a red test from the collection."""
    lifted = function.split(b"\n", 1)[1]
    lift = Change("tests/test_count.py", "M", function, lifted)
    project = b'[project]\nname = "rezono-compiler"\n'
    plugin = project + b'\n[project.entry-points.pytest11]\nx = "rezono_compiler.tidy"\n'
    poetry = project + b'\n[tool.poetry.plugins."pytest11"]\nx = "rezono_compiler.tidy"\n'
    config = b"[metadata]\nname = demo\n"
    entry = config + b"\n[options.entry_points]\npytest11 =\n    x = demo.tidy\n"
    hook = Change("compiler/rezono_compiler/tidy.py", "A", None, None)
    cases = [
        ("pytest11 entry point added to pyproject.toml", "compiler/pyproject.toml", project, plugin, True),
        ("pytest11 plugin added in poetry's table", "compiler/pyproject.toml", project, poetry, True),
        ("pytest11 entry point removed from pyproject.toml", "loop/pyproject.toml", plugin, project, True),
        ("pytest11 entry point added to setup.cfg", "demo/setup.cfg", config, entry, True),
        ("other metadata of pyproject.toml", "compiler/pyproject.toml", plugin,
         plugin.replace(b"rezono-compiler", b"rezono-compiler2"), False),
        ("pyproject.toml that no longer parses", "compiler/pyproject.toml", plugin, plugin + b"[[[\n", True),
        ("pyproject.toml replaced by a link", "compiler/pyproject.toml", plugin, UNREADABLE_CONFIG, True),
        # Entry points from elsewhere: the file they come from is not read, so the switch counts.
        ("dynamic entry points in pyproject.toml", "compiler/pyproject.toml", project,
         project + b'dynamic = ["entry-points"]\n\n[tool.setuptools.dynamic]\nentry-points = {file = ["eps.ini"]}\n',
         True),
        ("entry points from a file in setup.cfg", "demo/setup.cfg", config,
         config + b"\n[options]\nentry_points = file: eps.cfg\n", True),
    ]
    for label, path, before, after, expected in cases:
        change = Change(path, "M", before, after)
        errors, notes = review([change], planner=False)
        if bool(errors) != expected or (f"CHANGED {path} pytest plugins" in notes) != expected:
            raise AssertionError(f"{label}: errors {errors}, notes {notes}")
        errors, _ = review([lift, hook, change], planner=True)
        refused = any("Lift marks in a pull request of their own" in e for e in errors)
        if refused != expected:
            raise AssertionError(f"{label} beside a lifted mark: errors {errors}")
        print(f"{'DENY' if expected else 'ALLOW'} without planner and beside a lifted mark: {label}")
    # Python runs these before pytest starts; setup.py stays source as well.
    # Package metadata on sys.path registers plugins too, such as a *.dist-info in scripts/.
    for path in ("compiler/sitecustomize.py", "src/usercustomize.py", "compiler/rezono.pth", "compiler/setup.py",
                 "scripts/tidy-1.0.dist-info/entry_points.txt", "scripts/tidy-1.0.dist-info/METADATA",
                 "compiler/tidy.egg-info/PKG-INFO", "loop/entry_points.txt"):
        errors, _ = review([Change(path, "A", None, b"import tidy\n")], planner=False)
        if errors != [f"ERROR planner label required for {ascii(path)}"]:
            raise AssertionError(f"{path} without planner: errors {errors}")
        errors, _ = review([lift, Change(path, "A", None, b"import tidy\n")], planner=True)
        if not any("Lift marks in a pull request of their own" in e for e in errors):
            raise AssertionError(f"lifted mark beside {path}: errors {errors}")
        print(f"DENY without planner and beside a lifted mark: {path}")
    # CI reads the allowed plugins from the base; a change to the list is policy.
    errors, _ = review([Change("scripts/pytest-plugins.txt", "M", b"a = a\n", b"a = a\nx = tidy\n")], planner=False)
    if errors != ["ERROR planner label required for 'scripts/pytest-plugins.txt'"]:
        raise AssertionError(f"scripts/pytest-plugins.txt without planner: errors {errors}")
    print("DENY without planner: scripts/pytest-plugins.txt")
    if not source("compiler/setup.py"):
        raise AssertionError("setup.py is source as well")


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
        Change("k8s-admission/test_policy_shell.py", "M", b"a = 1\n", b"a = 2\n"),
    ], ["planner"], False)
    for path in ("checker/rezono_checker/proof.py", "packs/std-access/rules/access.dl",
                 "edge/gate/src/ask.ts", "edge/publisher/rezono_publisher/access.py",
                 "contracts/proof.yaml", "checker/rezono_checker/fixtures.py",
                 "k8s-admission/admission_translator.py", "k8s-admission/resources/publication-crd.yaml",
                 "k8s-admission/fixtures/managed-blue.yaml", "examples/platform/network_policy.py",
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


def decision_citation_cases():
    """Added or edited red marks must cite an existing headed decision, and the legacy budget only shrinks."""
    headed = (
        b"---\n"
        b"decider: [loop, core]\n"
        b"decided_on: 2026-11-20\n"
        b"valid_from: 2026-11-20\n"
        b"state: in_force\n"
        b"subject: sample-rule\n"
        b"---\n\n"
        b"# Sample headed decision\n"
    )
    proposed = (
        b"---\n"
        b"decider: [loop]\n"
        b"state: proposed\n"
        b"subject: draft-rule\n"
        b"---\n\n"
        b"# Proposed decision\n"
    )
    headless = b"# Legacy decision without head\n"
    for label, blob, expected in (
        ("valid in_force head", headed, True),
        ("valid proposed head without dates", proposed, True),
        ("valid head with valid_until and supersedes",
         headed.replace(b"state: in_force\n", b"valid_until: 2026-12-01\nstate: in_force\nsupersedes: [old-rule]\n"),
         True),
        ("headless markdown", headless, False),
        ("quoted date", headed.replace(b"2026-11-20", b'"2026-11-20"', 1), False),
        ("invalid calendar date", headed.replace(b"2026-11-20", b"2026-02-30", 1), False),
        ("unknown field", headed.replace(b"state: in_force\n", b"state: in_force\nowner: [loop]\n"), False),
        ("missing valid_from when in_force", headed.replace(b"valid_from: 2026-11-20\n", b""), False),
        ("valid_until not after valid_from",
         headed.replace(b"state: in_force\n", b"valid_until: 2026-11-20\nstate: in_force\n"), False),
        ("empty decider", headed.replace(b"[loop, core]", b"[]"), False),
        ("unknown decider", headed.replace(b"[loop, core]", b"[board]"), False),
        ("unknown state", headed.replace(b"in_force", b"settled"), False),
        ("bad subject", headed.replace(b"sample-rule", b"Sample_Rule"), False),
        ("missing empty line before title", headed.replace(b"---\n\n# ", b"---\n# "), False),
        ("missing title", headed.replace(b"# Sample headed decision", b"Sample headed decision"), False),
        ("unclosed head", headed.replace(b"---\n\n# ", b"\n# "), False),
        ("invalid UTF-8", b"\xff\xfe", False),
    ):
        actual = has_valid_decision_head(blob)
        if actual != expected:
            raise AssertionError(f"has_valid_decision_head({label}): expected {expected}, got {actual}")
        print(f"{'VALID' if actual else 'INVALID'} decision head: {label}")

    def test_src(reason):
        return (
            "import pytest\n\n" + "@" + f"pytest.mark.xfail(strict=True, reason={reason!r})\n"
            "def test_case():\n    assert False\n"
        ).encode("utf-8")

    for reason, expected in (
        ("M3: decisions/headed.md: section 1", "decisions/headed.md"),
        ("extra: decisions/headed.md", "decisions/headed.md"),
        ("later: decisions/a-1.md next", "decisions/a-1.md"),
        ("M3: missing citation", None),
        ("M3: mentions decisions/headed.md too late", None),
        ("decisions/headed.md: no milestone", None),
    ):
        _, mark = inventory(test_src(reason)).marks[0]
        actual = decision_citation(mark)
        if actual != expected:
            raise AssertionError(f"decision_citation({reason!r}): expected {expected!r}, got {actual!r}")

    files = {
        "decisions/headed.md": headed,
        "decisions/headless.md": headless,
        "decisions/broken.md": headed.replace(b"2026-11-20", b'"2026-11-20"', 1),
    }
    head_tree = Tree(
        {**{p: "100644" for p in files}, "decisions/linked.md": "120000"},
        lambda p: files.get(p, headed),
    )

    for bad_reason in (
        "M3: missing decision citation",
        "extra: decisions/nonexistent.md: missing file",
        "extra: decisions/headless.md: no head",
        "M3: decisions/broken.md: malformed head",
        "M3: decisions/linked.md: symlink",
        "M3: mentions decisions/headed.md too late",
    ):
        errors, _ = review([Change("loop/tests/test_new.py", "A", None, test_src(bad_reason))],
                           planner=True, head_tree=head_tree)
        if not errors:
            raise AssertionError(f"expected refusal for {bad_reason!r}")
        print(f"DENY added red mark: {bad_reason}")

    for good_reason in ("M3: decisions/headed.md: section 1.", "extra: decisions/headed.md: section 2."):
        errors, _ = review([Change("loop/tests/test_new.py", "A", None, test_src(good_reason))],
                           planner=True, head_tree=head_tree)
        if errors:
            raise AssertionError(f"unexpected refusal for {good_reason!r}: {errors}")
        print(f"ALLOW added red mark: {good_reason}")

    legacy = test_src("M3: legacy uncited reason")
    for planner_flag in (False, True):
        errors, _ = review([Change("loop/tests/test_legacy.py", "M", legacy, test_src("M3: still uncited"))],
                           planner=planner_flag, head_tree=head_tree)
        if not errors:
            raise AssertionError(f"expected refusal on edited legacy mark (planner={planner_flag})")
        errors, _ = review([Change("loop/tests/test_legacy.py", "M", legacy,
                                   test_src("M3: decisions/headed.md: cited now"))],
                           planner=planner_flag, head_tree=head_tree)
        if errors:
            raise AssertionError(f"unexpected refusal when citing headed decision (planner={planner_flag}): {errors}")

    both = (
        legacy + b"\n" + b"@"
        + b"pytest.mark.xfail(strict=True, reason='extra: decisions/headed.md: ok')\ndef test_two():\n    assert False\n"
    )
    errors, _ = review([Change("loop/tests/test_legacy.py", "M", legacy, both)], planner=True, head_tree=head_tree)
    if errors:
        raise AssertionError(f"untouched legacy mark should stay green: {errors}")

    budget = lambda items: (json.dumps(sorted(items), indent=2) + "\n").encode("utf-8")
    before = budget(["loop/tests/test_legacy.py::test_case", "loop/tests/test_other.py::test_other"])
    shrunk = budget(["loop/tests/test_other.py::test_other"])
    grown = budget(["loop/tests/test_added.py::test_added", "loop/tests/test_legacy.py::test_case",
                    "loop/tests/test_other.py::test_other"])
    unsorted = b'[\n  "loop/tests/test_other.py::test_other",\n  "loop/tests/test_legacy.py::test_case"\n]\n'
    duped = b'[\n  "loop/tests/test_other.py::test_other",\n  "loop/tests/test_other.py::test_other"\n]\n'
    lifted = b"import pytest\n\ndef test_case():\n    assert False\n"

    for planner_flag in (False, True):
        errors, _ = review([
            Change("loop/tests/test_legacy.py", "M", legacy, lifted),
            Change(RED_DECISION_BUDGET, "M", before, shrunk),
        ], planner=planner_flag, head_tree=head_tree)
        if errors:
            raise AssertionError(f"shrinking budget alongside lift failed (planner={planner_flag}): {errors}")
        for label, change in (
            ("grown budget", Change(RED_DECISION_BUDGET, "M", before, grown)),
            ("unsorted budget", Change(RED_DECISION_BUDGET, "M", before, unsorted)),
            ("duplicate budget", Change(RED_DECISION_BUDGET, "M", before, duped)),
            ("malformed budget", Change(RED_DECISION_BUDGET, "M", before, b"{}\n")),
            ("deleted budget", Change(RED_DECISION_BUDGET, "D", before, None)),
        ):
            errors, _ = review([change], planner=planner_flag, head_tree=head_tree)
            if not errors:
                raise AssertionError(f"expected refusal for {label} (planner={planner_flag})")
    print("ALLOW shrink-only budget alongside lift; DENY growth, misformatting and deletion")


if __name__ == "__main__":
    main()
