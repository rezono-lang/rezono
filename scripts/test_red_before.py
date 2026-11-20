"""Regression cases for the base counterexample check, in throwaway Git repositories.

Needs pytest, because the two end-to-end cases run the added tests on the base.
"""
from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import red_guard
from red_guard import Change, listed_plugins
from red_before import added_tests

SCRIPT = HERE / "red_before.py"
BUGGY = b"def double(x):\n    return x + 2\n"
FIXED = b"def double(x):\n    return x * 2\n"
TESTS = b"from pkg.calc import double\n\n\ndef test_double_two():\n    assert double(2) == 4\n"
# Both pass on the fixed source. Only the second fails on the buggy base (6 is even; 5 is not 6).
STILL_PASSES = TESTS + b"\n\ndef test_double_is_even():\n    assert double(4) % 2 == 0\n"
FAILS_ON_BASE = TESTS + b"\n\ndef test_double_three():\n    assert double(3) == 6\n"
# The only added test is skipped on the base, so it does not show that it tells the base
# from the fix: always skipped, skipped by itself, or turned into an expected failure there.
ONLY_SKIPPED = (b"import pytest\n" + TESTS + b"\n\n"
                + b"@pytest.mark.skip(reason='needs a cluster')\n"
                + b"def test_double_three():\n    assert double(3) == 6\n")
SKIPS_ITSELF = (b"import pytest\n" + TESTS + b"\n\n"
                + b"def test_double_three():\n    pytest.importorskip('absent_module_for_this_check')\n"
                + b"    assert double(3) == 6\n")
XFAIL_CALL = (b"import pytest\n" + TESTS + b"\n\n"
              + b"def test_double_three():\n    if double(3) != 6:\n        pytest.xfail('old source')\n"
              + b"    assert double(3) == 6\n")
# A test whose every case carries the cluster mark runs on the disposable cluster instead.
ONLY_CLUSTER = (b"import pytest\n" + TESTS + b"\n\n"
                + b"@pytest.mark.cluster\n"
                + b"def test_double_three():\n    assert double(3) == 6\n")
CLUSTER_AND_SKIPPED = (ONLY_CLUSTER + b"\n\n"
                       + b"@pytest.mark.skip(reason='later')\n"
                       + b"def test_double_four():\n    assert double(4) == 8\n")
# Stands in for the cluster plugin, so the cases do not depend on whether it is installed:
# cluster cases are deselected outside the disposable cluster.
CONFTEST = (b"def pytest_configure(config):\n"
            b"    config.addinivalue_line('markers', 'cluster: runs on the disposable cluster')\n\n\n"
            b"def pytest_collection_modifyitems(config, items):\n"
            b"    cluster = [item for item in items if item.get_closest_marker('cluster')]\n"
            b"    if cluster:\n"
            b"        items[:] = [item for item in items if not item.get_closest_marker('cluster')]\n"
            b"        config.hook.pytest_deselected(items=cluster)\n")


def git(repo, *args):
    return subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.org",
                           *args],
                          cwd=repo, check=True, capture_output=True).stdout.decode().strip()


def commit(repo, files):
    for name, data in files.items():
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "change")
    return git(repo, "rev-parse", "HEAD")


def script(repo, *args):
    return subprocess.run([sys.executable, "-I", str(SCRIPT), *args], cwd=repo, capture_output=True)


def end_to_end(label, added, expected_code, verdict):
    """A fix to double() with a new test: red when the test also passes on the base."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        repo = Path(directory)
        git(repo, "init", "-q")
        git(repo, "config", "core.autocrlf", "false")
        base = commit(repo, {"pytest.ini": b"[pytest]\n", "conftest.py": CONFTEST, "pkg/__init__.py": b"",
                             "pkg/calc.py": BUGGY, "tests/test_calc.py": TESTS})
        head = commit(repo, {"pkg/calc.py": FIXED, "tests/test_calc.py": added})
        found = script(repo, "discover", base, head)
        if found.returncode or found.stdout.decode().strip() != "required=true":
            raise AssertionError(f"{label}: discover gave {found.stdout!r} {found.stderr!r}")
        selection = repo.parent / f"{repo.name}-selection.txt"
        try:
            prepared = script(repo, "prepare", base, head, str(selection))
            if prepared.returncode:
                raise AssertionError(f"{label}: prepare failed: {prepared.stderr!r}")
            if (repo / "pkg/calc.py").read_bytes() != BUGGY or (repo / "tests/test_calc.py").read_bytes() != added:
                raise AssertionError(f"{label}: prepare did not lay the new tests over the base source")
            ran = script(repo, "run", str(selection))
        finally:
            selection.unlink(missing_ok=True)
        if ran.returncode != expected_code or verdict not in ran.stdout.decode():
            raise AssertionError(f"{label}: run exited {ran.returncode}, expected {expected_code}\n"
                                 f"{ran.stdout.decode()}{ran.stderr.decode()}")
        print(f"{'RED' if expected_code else 'GREEN'}: {label}")


def not_mixed():
    """Pull requests that change no source: nothing runs on the base."""
    red = TESTS.replace(b"def test_double_two", b"@pytest.mark.xfail(strict=True)\ndef test_double_two")
    cases = [
        ("added tests beside documentation only",
         {"pkg/calc.py": BUGGY, "tests/test_calc.py": TESTS},
         {"docs/calc.md": b"# Calc\n", "tests/test_calc.py": FAILS_ON_BASE}),
        ("lifted mark beside an added evidence file and source",
         {"pkg/calc.py": BUGGY, "tests/test_calc.py": b"import pytest\n" + red},
         {"pkg/calc.py": FIXED, "tests/test_calc.py": b"import pytest\n" + TESTS,
          "tests/cases/double.json": b"[4]\n"}),
    ]
    for label, before, after in cases:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
            repo = Path(directory)
            git(repo, "init", "-q")
            git(repo, "config", "core.autocrlf", "false")
            base = commit(repo, before)
            head = commit(repo, after)
            found = script(repo, "discover", base, head)
            if found.returncode or found.stdout.decode().strip() != "required=false":
                raise AssertionError(f"{label}: discover gave {found.stdout!r} {found.stderr!r}")
            print(f"SKIP: {label}")


def selection_cases():
    marked = b"@pytest.mark.xfail(strict=True)\n"
    new_test = b"def test_new():\n    assert True\n"
    cases = [
        ("added test", [Change("tests/test_a.py", "A", None, new_test)], ["tests/test_a.py::test_new"]),
        ("added test with a red mark", [Change("tests/test_a.py", "A", None, marked + new_test)], []),
        ("added test in a red class", [Change("tests/test_a.py", "A", None, marked + b"class TestA:\n"
                                              + b"    def test_new(self):\n        pass\n")], []),
        ("added test in a red module",
         [Change("tests/test_a.py", "A", None, b"pytestmark = " + marked[1:] + new_test)], []),
        ("added test with a red parameter", [Change("tests/test_a.py", "A", None,
         b"@pytest.mark.parametrize('v', [pytest.param(1, marks=pytest.mark.xfail(strict=True))])\n"
         b"def test_new(v):\n    pass\n")], []),
        ("changed existing test", [Change("tests/test_a.py", "M", new_test, new_test.replace(b"True", b"False"))], []),
        ("lifted mark", [Change("tests/test_a.py", "M", marked + new_test, new_test)], []),
        ("added helper outside a test file", [Change("tests/support_a.py", "A", None, new_test)], []),
        ("added test method in a Test class", [Change("tests/test_a.py", "A", None,
         b"class TestA:\n    def test_new(self):\n        pass\n")], ["tests/test_a.py::TestA::test_new"]),
    ]
    for label, records, expected in cases:
        actual = added_tests(records)
        if actual != expected:
            raise AssertionError(f"{label}: expected {expected}, got {actual}")
        print(f"SELECT {len(actual)}: {label}")


# Reads its expectation from evidence data that the base does not have yet.
READS_CASE = (b"import json\nfrom pathlib import Path\n\nimport pytest\n\nfrom pkg.calc import double\n\n\n"
              b"@pytest.mark.xfail(strict=True, raises=FileNotFoundError, reason=\"M1: needs the case\")\n"
              b"def test_double_case():\n"
              b"    expected = json.loads((Path(__file__).parent / 'expected/double.json').read_text())\n"
              b"    assert double(2) == expected[0]\n")


PARAM_MARK = b'pytest.mark.xfail(strict=True, raises=FileNotFoundError, reason="M1: needs the case")'
# A smoke case that passes anywhere, and a red case that reads the evidence.
PARAM_CASE = (b"import json\nfrom pathlib import Path\n\nimport pytest\n\nfrom pkg.calc import double\n\n\n"
              b"@pytest.mark.parametrize('case', ['smoke', pytest.param('case', marks=" + PARAM_MARK + b")])\n"
              b"def test_double_case(case):\n"
              b"    if case == 'smoke':\n"
              b"        assert double(1) == 2\n"
              b"        return\n"
              b"    expected = json.loads((Path(__file__).parent / 'expected/double.json').read_text())\n"
              b"    assert double(2) == expected[0]\n")


def completion(label, test, case, run_code, green_code, verdict, lifted=None):
    """One lifted mark beside only the evidence data its test reads: red on the base, green after."""
    if lifted is None:
        lifted = test.replace(b"@" + PARAM_MARK + b"\n", b"")
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        repo = Path(directory)
        git(repo, "init", "-q")
        git(repo, "config", "core.autocrlf", "false")
        base = commit(repo, {"pytest.ini": b"[pytest]\n", "conftest.py": CONFTEST, "pkg/__init__.py": b"",
                             "pkg/calc.py": FIXED, "tests/test_calc.py": test})
        head = commit(repo, {"tests/test_calc.py": lifted, "tests/expected/double.json": case})
        found = script(repo, "discover", base, head)
        if found.returncode or found.stdout.decode().strip() != "required=true":
            raise AssertionError(f"{label}: discover gave {found.stdout!r} {found.stderr!r}")
        selection = repo.parent / f"{repo.name}-selection.txt"
        try:
            prepared = script(repo, "prepare", base, head, str(selection))
            if prepared.returncode or selection.read_text() != "tests/test_calc.py::test_double_case\n":
                raise AssertionError(f"{label}: prepare failed: {prepared.stderr!r}")
            if (repo / "tests/test_calc.py").read_bytes() != lifted or (repo / "tests/expected/double.json").exists():
                raise AssertionError(f"{label}: prepare did not lay only the lifted test over the base")
            ran = script(repo, "run", str(selection))
            done = script(repo, "green", base, head, str(selection)) if not ran.returncode else ran
        finally:
            selection.unlink(missing_ok=True)
        output = ran.stdout.decode() + done.stdout.decode()
        if ran.returncode != run_code or done.returncode != green_code or verdict not in output:
            raise AssertionError(f"{label}: run exited {ran.returncode}, green exited {done.returncode}\n"
                                 f"{output}{ran.stderr.decode()}{done.stderr.decode()}")
        print(f"{'RED' if run_code or green_code else 'GREEN'}: {label}")


def base_list_cases():
    """In CI the plugin list comes from the base revision under GITHUB_SHA, not the checkout.

    red_guard.listed_plugins is the one reading of the list for components.py and red_before.py.
    """
    keys = ("GITHUB_ACTIONS", "GITHUB_EVENT_PATH", "GITHUB_SHA", "GITHUB_EVENT_NAME")
    saved = {key: os.environ.get(key) for key in keys}
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        repo = Path(directory)
        git(repo, "init", "-q")
        git(repo, "config", "core.autocrlf", "false")
        base = commit(repo, {"scripts/pytest-plugins.txt": b"# allowed\nlisted = listed\n"})
        head = commit(repo, {"scripts/pytest-plugins.txt": b"listed = listed\nadded = added\n"})
        git(repo, "checkout", "-q", base)
        git(repo, "merge", "-q", "--no-ff", "-m", "merge", head)
        merge = git(repo, "rev-parse", "HEAD")
        event, local = repo / "event.json", repo / "scripts/pytest-plugins.txt"

        def listed(name, data, sha=merge, actions="true", path=event):
            event.write_text(json.dumps(data), encoding="utf-8")
            os.environ.update(GITHUB_ACTIONS=actions, GITHUB_SHA=sha, GITHUB_EVENT_NAME=name)
            os.environ.pop("GITHUB_EVENT_PATH", None)
            if path:
                os.environ["GITHUB_EVENT_PATH"] = str(path)
            return listed_plugins(local, repo)

        def refused(label, *args, **kwargs):
            try:
                listed(*args, **kwargs)
            except SystemExit as error:
                print(f"REFUSED: {label}: {error}")
                return
            raise AssertionError(f"{label} was not refused")

        try:
            for name, data in (("pull_request", {"pull_request": {"base": {"sha": base}}}),
                               ("merge_group", {"merge_group": {"base_sha": base}})):
                if listed(name, data) != {"listed = listed"}:
                    raise AssertionError(f"{name}: the list does not come from the first parent of GITHUB_SHA")
                print(f"BASE: the plugin list of a {name} comes from the first parent of GITHUB_SHA")
            if listed("push", {}, sha=base) != {"listed = listed"}:
                raise AssertionError("push: the list does not come from GITHUB_SHA")
            print("BASE: the plugin list of a push comes from GITHUB_SHA")
            # pull_request_target runs on the base branch's own commit, so GITHUB_SHA is the base.
            if listed("pull_request_target", {}, sha=base) != {"listed = listed"}:
                raise AssertionError("pull_request_target: the list does not come from GITHUB_SHA")
            print("BASE: the plugin list of pull_request_target comes from GITHUB_SHA")
            # A graft that gives the merge commit the head as its first parent moves nothing.
            grafts = repo / ".git/info/grafts"
            grafts.parent.mkdir(parents=True, exist_ok=True)
            grafts.write_text(f"{merge} {head}\n", encoding="utf-8")
            try:
                if listed("pull_request", {}) != {"listed = listed"}:
                    raise AssertionError("a graft moved the base of the plugin list")
            finally:
                grafts.unlink()
            print("BASE: a graft in .git/info/grafts does not move the base")
            # The event file does not decide the base: one that names another commit changes nothing.
            if listed("pull_request", {"pull_request": {"base": {"sha": head}}}) != {"listed = listed"}:
                raise AssertionError("an event that names another base moved the list")
            print("BASE: an event that names another base does not move the list")
            refused("GitHub Actions without an event file", "pull_request", {}, path=None)
            # A base that cannot be fetched after three attempts stops the run.
            sleep, red_guard.time.sleep = red_guard.time.sleep, lambda seconds: None
            try:
                refused("a base that cannot be fetched", "push", {}, sha="0" * 40)
            finally:
                red_guard.time.sleep = sleep
            if listed("pull_request", {}, actions="false", path=None) != {"listed = listed", "added = added"}:
                raise AssertionError("outside CI the checkout's list applies")
            print("LOCAL: outside CI the checkout's plugin list applies")
        finally:
            for key, value in saved.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value


def main():
    base_list_cases()
    # The cases below run in repositories of their own, without the job's base revision, so
    # they read the plugin list from their checkout.
    os.environ.pop("GITHUB_ACTIONS", None)
    selection_cases()
    not_mixed()
    completion("evidence completion: red on the base, green with the new evidence", READS_CASE, b"[4]\n",
               0, 0, "The completed test is red on the base and passes with the new evidence")
    completion("evidence completion whose evidence does not make the test pass", READS_CASE, b"[5]\n",
               0, 1, "ERROR the completed test does not pass in every case with the new evidence")
    # Another case passes, but the case that reads the evidence skips or xfails with it: that
    # shows nothing about the evidence.
    for outcome in (b"skip", b"xfail"):
        test = PARAM_CASE.replace(b"    assert double(2) == expected[0]\n",
                                  b"    pytest." + outcome + b"('evidence present')\n")
        completion(f"evidence completion whose case calls pytest.{outcome.decode()} with the evidence",
                   test, b"[4]\n", 0, 1, "ERROR the completed test does not pass in every case with the new evidence",
                   lifted=test.replace(b"pytest.param('case', marks=" + PARAM_MARK + b")", b"pytest.param('case')"))
    completion("evidence completion whose test passes on the base without the evidence",
               READS_CASE.replace(b"    expected = json.loads", b"    return\n    expected = json.loads"),
               b"[4]\n", 1, 1, "pass on the base source")
    end_to_end("source fix with an added test that also passes on the base", STILL_PASSES, 1,
               "pass on the base source")
    end_to_end("source fix with an added test that fails on the base", FAILS_ON_BASE, 0,
               "The base source fails the added tests")
    end_to_end("source fix with only an always skipped added test", ONLY_SKIPPED, 1,
               "ERROR none of the 1 added test(s)")
    end_to_end("source fix with only an added test that skips itself", SKIPS_ITSELF, 1,
               "ERROR none of the 1 added test(s)")
    end_to_end("source fix with only an added test that calls pytest.xfail on the base", XFAIL_CALL, 1,
               "ERROR none of the 1 added test(s)")
    end_to_end("source fix with a skipped added test beside a cluster test", CLUSTER_AND_SKIPPED, 1,
               "ERROR none of the 2 added test(s)")
    end_to_end("source fix with only an added cluster test", ONLY_CLUSTER, 0,
               "they run on the disposable cluster instead")


if __name__ == "__main__":
    main()
