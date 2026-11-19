"""Exercise the check on references to missing docs pages in a throwaway repository, using only the standard library."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("docs_links.py").resolve()
# Assembled at run time so this file adds no reference to the repository's own count.
DOCS = "docs"


class DocsLinks(unittest.TestCase):
    def run_check(self, files, budget=None, base_budget=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            (root / "scripts").mkdir()
            budget_file = root / "scripts" / "docs-link-budget.json"
            args = []
            if base_budget is not None:
                budget_file.write_text(json.dumps(base_budget))
                subprocess.check_call(["git", "add", "-A"], cwd=root)
                subprocess.check_call(
                    ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "base"], cwd=root
                )
                args = ["--base", "HEAD"]
            budget_file.write_text(json.dumps(budget or {}))
            for name, text in files.items():
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text(text)
            subprocess.check_call(["git", "add", "-A"], cwd=root)
            return subprocess.run(
                [sys.executable, "-I", str(SCRIPT), *args], cwd=root, capture_output=True, text=True
            )

    def test_new_reference_to_a_missing_page_is_red(self):
        result = self.run_check({"README.md": f"See [the guide]({DOCS}/guide.md#start).\n"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{DOCS}/guide.md: observed=1 listed=0", result.stdout)

    def test_more_references_than_the_budget_is_red(self):
        text = f"{DOCS}/guide.md and {DOCS}/guide.md\n"
        result = self.run_check({"notes.py": text}, budget={f"{DOCS}/guide.md": 1})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{DOCS}/guide.md: observed=2 listed=1", result.stdout)

    def test_fewer_references_pass_and_ask_to_lower_the_budget(self):
        result = self.run_check({"notes.py": f"{DOCS}/guide.md\n"}, budget={f"{DOCS}/guide.md": 3})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(f"{DOCS}/guide.md: observed=1 listed=3; lower the budget", result.stdout)

    def test_raising_the_budget_above_the_base_is_red(self):
        files = {"notes.py": f"{DOCS}/guide.md {DOCS}/guide.md\n"}
        result = self.run_check(files, budget={f"{DOCS}/guide.md": 2}, base_budget={f"{DOCS}/guide.md": 1})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("exceeds the base budget 1", result.stdout)

    def test_existing_pages_and_folders_are_not_counted(self):
        files = {
            f"{DOCS}/guide.md": "# Guide\n",
            f"{DOCS}/cases/E1.yaml": "case: 1\n",
            "README.md": f"[g]({DOCS}/guide.md) [c]({DOCS}/cases/) [e](./{DOCS}/cases/E1.yaml)\n",
        }
        result = self.run_check(files)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("missing_pages=0 references=0", result.stdout)

    def test_relative_links_resolve_from_the_file(self):
        result = self.run_check({"admission/README.md": f"[live](../{DOCS}/live.md)\n"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{DOCS}/live.md: observed=1 listed=0", result.stdout)

    def test_a_path_in_another_projects_url_does_not_count(self):
        text = (
            f"https://raw.githubusercontent.com/argoproj/argo-cd/v3.0.0/{DOCS}/operator-manual/x.md\n"
            f"https://codeberg.org/forgejo/{DOCS}/raw/branch/v9.0/{DOCS}/admin/y.md\n"
            f"kubernetes.io/{DOCS}/reference/z.md\n"
        )
        result = self.run_check({"facts.yaml": text})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("missing_pages=0 references=0", result.stdout)

    def test_a_url_into_this_repository_counts(self):
        text = f"https://github.com/rezono-lang/rezono/blob/main/{DOCS}/guide.md\n"
        result = self.run_check({"README.md": text})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn(f"{DOCS}/guide.md: observed=1 listed=0", result.stdout)


if __name__ == "__main__":
    unittest.main()
