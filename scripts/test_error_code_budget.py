"""Hold the compiler's error-code budget to the budget on the base, cell by cell, using only the standard library.

compiler/tests/test_error_codes.py requires the error sites without a code to stay within
compiler/error-code-budget.json, cell by cell. This check requires each cell of that budget (one file, one
class) to be at most the same cell on the base commit, so the budget never rises and a new site in one
cell cannot be paid for by a code in another (decisions/compiler-error-codes.md).

With ERROR_CODE_BUDGET_BASE set to a commit, the last test compares the working tree with that
commit; without it, that test is skipped and only the comparison itself is exercised.
"""

import json
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parent.parent
BUDGET = "compiler/error-code-budget.json"
BASE = "ERROR_CODE_BUDGET_BASE"


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
