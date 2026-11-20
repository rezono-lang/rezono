"""Hold the compiler's error-code budget to the budget on the base, cell by cell, using only the standard library.

compiler/tests/test_error_codes.py requires the error sites without a code to stay within
compiler/error-code-budget.json, cell by cell. This check requires each cell of that budget (one file, one
class) to be at most the same cell on the base commit, so the budget never rises and a new site in one
cell cannot be paid for by a code in another (decisions/compiler-error-codes.md).

It also holds the sites themselves to the base: each cell's count of sites without a code in the working tree
is at most the same cell's count on the base. The budget is a ceiling that need not fall when a site gets a
code, so without this ratchet the room left behind could take a new site without a code in a later change.
The sites are counted with `uncoded` from compiler/tests/test_error_codes.py, read from its source so the two
checks share one rule.

With ERROR_CODE_BUDGET_BASE set to a commit, the base tests compare the working tree with that commit;
without it, they are skipped and only the comparisons themselves are exercised.
"""

import ast

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from collections import Counter


ROOT = Path(__file__).resolve().parent.parent
BUDGET = "compiler/error-code-budget.json"
BASE = "ERROR_CODE_BUDGET_BASE"
SOURCE = "compiler/rezono_compiler"
COUNTER = ROOT / "compiler" / "tests" / "test_error_codes.py"
COUNTER_NAMES = {"COUNTED", "FORWARDS", "COLLECTED", "_name", "uncoded"}


def load_uncoded():
    """`uncoded` from the compiler's error-code test, with only the definitions it needs (no test imports)."""
    tree = ast.parse(COUNTER.read_text("utf-8"))
    kept = [node for node in tree.body
            if (isinstance(node, ast.FunctionDef) and node.name in COUNTER_NAMES)
            or (isinstance(node, ast.Assign) and {getattr(t, "id", None) for t in node.targets} & COUNTER_NAMES)]
    if {getattr(n, "name", None) or n.targets[0].id for n in kept} != COUNTER_NAMES:
        raise ValueError(f"{COUNTER}: expected definitions of {sorted(COUNTER_NAMES)}")
    namespace = {"ast": ast, "Counter": Counter}
    exec(compile(ast.Module(body=kept, type_ignores=[]), str(COUNTER), "exec"), namespace)
    return namespace["uncoded"]


def site_counts(files, uncoded):
    """{file: {class: n}} for an iterable of (path, text), leaving out files without a site."""
    out = {}
    for path, text in files:
        found = uncoded(text)
        if found:
            out[path] = dict(sorted(found.items()))
    return out


def git(*arguments):
    return subprocess.check_output(["git", *arguments], cwd=ROOT)


def base_files(base):
    names = git("ls-tree", "-r", "--name-only", base, "--", SOURCE).decode().split()
    return ((name, git("show", f"{base}:{name}").decode("utf-8")) for name in names if name.endswith(".py"))


def tree_files():
    return ((path.relative_to(ROOT).as_posix(), path.read_text("utf-8"))
            for path in sorted((ROOT / SOURCE).rglob("*.py")))


def read_budget(data):
    """A budget is an object of files, each an object of classes with a positive whole count."""
    budget = json.loads(data)
    if not isinstance(budget, dict):
        raise ValueError("Expected an object of files")
    for path, cells in budget.items():
        if not isinstance(cells, dict) or not cells:
            raise ValueError(f"{path}: expected a nonempty object of classes")
        if any(type(number) is not int or number <= 0 for number in cells.values()):
            raise ValueError(f"{path}: counts must be positive whole numbers")
    return budget


def rises(base, budget):
    """The cells of `budget` above the same cell of `base`, as (file, class, listed, allowed)."""
    return [(path, name, number, base.get(path, {}).get(name, 0))
            for path, cells in sorted(budget.items()) for name, number in sorted(cells.items())
            if number > base.get(path, {}).get(name, 0)]


class ErrorCodeBudget(unittest.TestCase):
    BASE_BUDGET = {"a.py": {"CompileError": 3, "collected": 2}, "b.py": {"LoadError": 1}}

    def test_an_equal_or_lower_budget_passes(self):
        lower = {"a.py": {"CompileError": 2, "collected": 2}}
        self.assertEqual(rises(self.BASE_BUDGET, self.BASE_BUDGET), [])
        self.assertEqual(rises(self.BASE_BUDGET, lower), [])

    def test_a_raised_cell_is_refused(self):
        raised = {"a.py": {"CompileError": 4, "collected": 2}, "b.py": {"LoadError": 1}}
        self.assertEqual(rises(self.BASE_BUDGET, raised), [("a.py", "CompileError", 4, 3)])

    def test_a_new_cell_is_refused_even_when_another_cell_drops_by_as_much(self):
        swapped = {"a.py": {"CompileError": 2, "collected": 2, "OperationError": 1}, "b.py": {"LoadError": 1}}
        moved = {"a.py": {"CompileError": 3, "collected": 2}, "c.py": {"LoadError": 1}}
        self.assertEqual(rises(self.BASE_BUDGET, swapped), [("a.py", "OperationError", 1, 0)])
        self.assertEqual(rises(self.BASE_BUDGET, moved), [("c.py", "LoadError", 1, 0)])

    def test_a_malformed_budget_is_refused(self):
        for text in ("[]", '{"a.py": {}}', '{"a.py": {"CompileError": 0}}', '{"a.py": {"CompileError": true}}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                read_budget(text)

    def test_sites_without_a_code_are_counted_with_the_compiler_test_rule(self):
        uncoded = load_uncoded()
        text = "raise CompileError('x')\nraise LoadError('y', code='c')\nerrors.append('z')\n"
        self.assertEqual(site_counts([("a.py", text), ("b.py", "pass\n")], uncoded),
                         {"a.py": {"CompileError": 1, "collected": 1}})

    def test_a_coded_site_leaves_no_room_for_a_new_one(self):
        # The budget still lists 3 after one site got a code; the next change may not use the room.
        base = {"a.py": {"CompileError": 2}}
        self.assertEqual(rises(base, {"a.py": {"CompileError": 2}}), [])
        self.assertEqual(rises(base, {"a.py": {"CompileError": 3}}), [("a.py", "CompileError", 3, 2)])

    @unittest.skipUnless(os.environ.get(BASE), f"{BASE} names no base commit")
    def test_sites_without_a_code_stay_within_the_base_count(self):
        uncoded = load_uncoded()
        previous = site_counts(base_files(os.environ[BASE]), uncoded)
        current = site_counts(tree_files(), uncoded)
        found = rises(previous, current)
        self.assertEqual(found, [], "\n".join(
            f"{path} {name}: {number} sites without a code, above {allowed} on the base" for path, name, number, allowed
            in found))

    @unittest.skipUnless(os.environ.get(BASE), f"{BASE} names no base commit")
    def test_the_budget_stays_within_the_base_budget(self):
        base = os.environ[BASE]
        listed = subprocess.run(["git", "ls-tree", "--name-only", base, "--", BUDGET],
                                cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
        if not listed:
            self.skipTest(f"{BUDGET} is not on the base {base}")
        previous = read_budget(subprocess.check_output(["git", "show", f"{base}:{BUDGET}"], cwd=ROOT))
        current = read_budget((ROOT / BUDGET).read_bytes())
        found = rises(previous, current)
        self.assertEqual(found, [], "\n".join(
            f"{path} {name}: listed={number} exceeds the base budget {allowed}" for path, name, number, allowed in found))


if __name__ == "__main__":
    sys.exit(unittest.main())
