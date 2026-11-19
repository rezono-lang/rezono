"""Regression cases for the base counterexample check, in throwaway Git repositories.

Needs pytest, because the two end-to-end cases run the added tests on the base.
"""
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from red_guard import Change
from red_before import added_tests

SCRIPT = HERE / "red_before.py"
BUGGY = b"def double(x):\n    return x + 2\n"
FIXED = b"def double(x):\n    return x * 2\n"
TESTS = b"from pkg.calc import double\n\n\ndef test_double_two():\n    assert double(2) == 4\n"
# Both pass on the fixed source. Only the second fails on the buggy base (6 is even; 5 is not 6).
STILL_PASSES = TESTS + b"\n\ndef test_double_is_even():\n    assert double(4) % 2 == 0\n"
FAILS_ON_BASE = TESTS + b"\n\ndef test_double_three():\n    assert double(3) == 6\n"
# The only added test is skipped: it runs nowhere, so it proves nothing on the base either.
ONLY_SKIPPED = (b"import pytest\n" + TESTS
                + b"\n\n@pytest.mark.skip(reason='needs a cluster')\ndef test_double_three():\n"
                + b"    assert double(3) == 6\n")


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
        base = commit(repo, {"pytest.ini": b"[pytest]\n", "pkg/__init__.py": b"",
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
        ("lifted mark beside an added evidence file",
         {"pkg/calc.py": FIXED, "tests/test_calc.py": b"import pytest\n" + red},
         {"tests/test_calc.py": b"import pytest\n" + TESTS, "tests/cases/double.json": b"[4]\n"}),
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


def main():
    selection_cases()
    not_mixed()
    end_to_end("source fix with an added test that also passes on the base", STILL_PASSES, 1,
               "pass on the base source")
    end_to_end("source fix with an added test that fails on the base", FAILS_ON_BASE, 0,
               "The base source fails the added tests")
    end_to_end("source fix with only a skipped added test", ONLY_SKIPPED, 0,
               "ran on the base source")


if __name__ == "__main__":
    main()
