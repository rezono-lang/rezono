"""Exercise the leak check on a throwaway repository, using only the standard library."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("leak_check.py").resolve()
# Assembled at run time so this file never contains the private pack name itself.
PACK_NAME = "".join(("at", "las"))


class LeakCheck(unittest.TestCase):
    def run_check(self, files):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            (root / "scripts").mkdir()
            (root / "scripts" / "leak-budget.json").write_text("{}\n")
            for name, text in files.items():
                (root / name).write_text(text)
            subprocess.check_call(["git", "add", "-A"], cwd=root)
            return subprocess.run(
                [sys.executable, "-I", str(SCRIPT)], cwd=root, capture_output=True, text=True
            )

    def test_private_pack_name_is_found_in_any_case(self):
        for word in (PACK_NAME, PACK_NAME.title(), PACK_NAME.upper()):
            with self.subTest(case=word[:1]):
                result = self.run_check({"pack.yaml": f"pack: {word}\n"})
                self.assertEqual(result.returncode, 1)
                self.assertIn("pack.yaml old_name: observed=1 listed=0", result.stdout)
                self.assertNotIn(PACK_NAME, result.stdout.lower())

    def test_private_pack_name_in_a_filename_is_redacted(self):
        result = self.run_check({f"{PACK_NAME}.yaml": "pack: neutral\n"})
        self.assertEqual(result.returncode, 1)
        self.assertIn("[redacted filename] old_name: observed=1 listed=0", result.stdout)
        self.assertNotIn(PACK_NAME, result.stdout.lower())

    def test_longer_words_are_not_findings(self):
        result = self.run_check({"pack.yaml": f"pack: {PACK_NAME}es x{PACK_NAME}\n"})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("old_name=0", result.stdout)


class BranchName(unittest.TestCase):
    def run_branch(self, branch):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            (root / "scripts").mkdir()
            (root / "scripts" / "leak-budget.json").write_text("{}\n")
            subprocess.check_call(["git", "add", "-A"], cwd=root)
            return subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--branch", branch], cwd=root, capture_output=True, text=True
            )

    def test_names_after_a_subject_pass(self):
        for branch in ("fix/scripts-leak_check.py", "fix/scripts-red_guard.py-pins", "fix/github-workflows-ci.yml",
                       "fix/decisions-run-closed-month.md", "task/examples/platform/test_x.py--test_run_order",
                       "note/compiler/tests/test_lower_reason.py--test_lower_reason", "golf1/planner-decision-heads",
                       "test/std-access-oracle-trial", "dependabot/github_actions/actions-0984fe3082",
                       "golf1/planner-runtime-kernel"):
            with self.subTest(branch=branch):
                result = self.run_branch(branch)
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertNotIn("branch ", result.stdout)

    def test_a_stream_followed_by_a_number_is_refused(self):
        for branch in ("golf1/planner-kern-67-error-codes", "golf1/planner-taal-48-reasons", "golf-2/subject",
                       "fix/run-12-subject", "task/platform-62-capacity", "Kring-3-subject"):
            with self.subTest(branch=branch):
                result = self.run_branch(branch)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"branch {branch}: numbered_stream", result.stdout)

    def test_a_stream_as_a_segment_of_its_own_is_refused(self):
        for branch in ("golf1/planner-kern-std-table", "golf1/kern-ci-dedupe-impl", "kring-p14-keys",
                       "subject/run/fix", "golf1/planner-platform-subject"):
            with self.subTest(branch=branch):
                result = self.run_branch(branch)
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertIn(f"branch {branch}: stream_segment", result.stdout)


if __name__ == "__main__":
    unittest.main()
