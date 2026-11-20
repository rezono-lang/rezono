"""Exercise the leak check on a throwaway repository, using only the standard library."""

from pathlib import Path
import json
import os
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("leak_check.py").resolve()
# Assembled at run time so this file never contains the private pack name itself.
PACK_NAME = "".join(("at", "las"))
# Assembled at run time so this file never contains an address outside an example domain.
AUTHOR = "222310762+vdo89" + "@users.noreply.github.com"
FOREIGN = "someone" + "@" + "corp.net"
CLEAN = f"Add a pack reader\n\nGenerated with Claude Code\nSigned-off-by: vdo89 <{AUTHOR}>\n"
GIT = ["git", "-c", "user.name=vdo89", "-c", f"user.email={AUTHOR}", "-c", "commit.gpgsign=false"]


class LeakCheck(unittest.TestCase):
    def run_check(self, files, budget="{}\n", base_files=None, messages=(), event=None):
        """Check the files; with base_files, first commit those under the same budget and check against that base.
        With event, also commit one empty commit per message and check that range as the event."""
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside:
            root = Path(temp)
            subprocess.check_call(["git", "init", "-q"], cwd=root)
            (root / "scripts").mkdir()
            (root / "scripts" / "leak-budget.json").write_text(budget)
            options = []
            if base_files is not None:
                for name, text in base_files.items():
                    (root / name).write_text(text)
                subprocess.check_call(["git", "add", "-A"], cwd=root)
                git = ["git", "-c", "user.name=Base", "-c", "user.email=base@example.org", "-c", "commit.gpgsign=false"]
                subprocess.check_call([*git, "commit", "-q", "-m", "Base"], cwd=root)
                base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
                options = ["--base", base]
            for name, text in files.items():
                (root / name).write_text(text)
            subprocess.check_call(["git", "add", "-A"], cwd=root)
            # The check reads the CI event from the environment; never let the real one leak in.
            env = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
            if event is not None:
                subprocess.check_call([*GIT, "commit", "-q", "-m", "Start"], cwd=root)
                base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
                for message in messages:
                    subprocess.run(
                        [*GIT, "commit", "-q", "--allow-empty", "--cleanup=verbatim", "-F", "-"],
                        cwd=root, input=message.encode(), check=True,
                    )
                head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
                name, payload = event(base, head)
                path = Path(outside) / "event.json"
                path.write_text(json.dumps(payload))
                env.update(GITHUB_EVENT_NAME=name, GITHUB_EVENT_PATH=str(path))
            return subprocess.run(
                [sys.executable, "-I", str(SCRIPT), *options], cwd=root, capture_output=True, text=True, env=env
            )

    def run_pull_request(self, messages, title="Add a pack reader", body=""):
        def event(base, head):
            pull = {"base": {"sha": base}, "head": {"sha": head}, "title": title, "body": body}
            return "pull_request", {"pull_request": pull}

        return self.run_check({"pack.yaml": "pack: neutral\n"}, messages=messages, event=event)

    def test_clean_commit_messages_and_pull_request_pass(self):
        result = self.run_pull_request([CLEAN, "Fix the reader\n"], body="Generated with Claude Code\n")
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_co_authored_by_trailer_is_refused_in_any_case(self):
        for trailer in ("Co-authored-by", "co-authored-by", "CO-AUTHORED-BY"):
            with self.subTest(trailer=trailer):
                message = f"Add a pack reader\n\n{trailer}: Someone <someone@example.org>\n"
                result = self.run_pull_request([CLEAN, message])
                self.assertEqual(result.returncode, 1, result.stdout)
                self.assertRegex(result.stdout, r"commit [0-9a-f]+ message co_author: observed=1 allowed=0")

    def test_dependency_bot_sign_off_passes(self):
        sign_off = "Signed-off-by: dependabot[bot] <support" + "@github.com>"
        result = self.run_pull_request([f"Bump a tool\n\n{sign_off}\n"])
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_foreign_address_in_a_commit_message_is_refused(self):
        result = self.run_pull_request([f"Add a pack reader\n\nReported by {FOREIGN}\n"])
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertRegex(result.stdout, r"commit [0-9a-f]+ message email: observed=1 allowed=0")
        self.assertNotIn(FOREIGN, result.stdout)

    def test_pull_request_title_and_body_are_checked(self):
        result = self.run_pull_request([CLEAN], title=f"Add a reader for {FOREIGN}", body=f"Co-authored-by: X <{FOREIGN}>")
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("pull request title email: observed=1 allowed=0", result.stdout)
        self.assertIn("pull request body co_author: observed=1 allowed=0", result.stdout)
        self.assertIn("pull request body email: observed=1 allowed=0", result.stdout)

    def test_a_decorator_in_backticks_is_not_an_address(self):
        # Assembled at run time so the base leak check does not count the decorator as an address.
        text = "Lift the `" + "@" + "pytest.mark.xfail` mark and keep '" + "@" + "pytest.mark.skip' as it is.\n"
        result = self.run_pull_request([f"Lift a mark\n\n{text}"], body=text)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("email", result.stdout.replace("email=0", ""))

    def test_merge_group_squash_message_is_checked(self):
        squash = f"Add a pack reader (#7)\n\nCo-authored-by: Someone <{FOREIGN}>\n"

        def event(base, head):
            group = {"base_sha": base, "head_sha": head, "head_commit": {"message": squash}}
            return "merge_group", {"merge_group": group}

        result = self.run_check({"pack.yaml": "pack: neutral\n"}, messages=[squash], event=event)
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("merge group message co_author: observed=1 allowed=0", result.stdout)
        self.assertRegex(result.stdout, r"commit [0-9a-f]+ message email: observed=1 allowed=0")
        self.assertNotIn(FOREIGN, result.stdout)

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

    def test_budget_is_a_ceiling_that_may_fall(self):
        # Two changes that each remove a finding from one file merge into fewer findings than listed: still green.
        budget = '{"pack.yaml": {"old_name": 2}}\n'
        result = self.run_check({"pack.yaml": f"pack: {PACK_NAME}\n"}, budget=budget)
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("pack.yaml old_name: observed=1 listed=2; lower the budget", result.stdout)
        result = self.run_check({"pack.yaml": f"pack: {PACK_NAME}\nalso: {PACK_NAME}\nand: {PACK_NAME}\n"}, budget=budget)
        self.assertEqual(result.returncode, 1)
        self.assertIn("pack.yaml old_name: observed=3 listed=2", result.stdout)
        self.assertNotIn(PACK_NAME, result.stdout.lower())

    def test_a_new_finding_in_a_file_with_slack_is_refused(self):
        # The budget still lists 2 after one finding was removed; a new one may not fill that slack.
        budget = '{"pack.yaml": {"old_name": 2}}\n'
        result = self.run_check({"pack.yaml": f"pack: {PACK_NAME}\nalso: {PACK_NAME}\n"}, budget,
                                base_files={"pack.yaml": f"pack: {PACK_NAME}\n"})
        self.assertEqual(result.returncode, 1, result.stdout)
        self.assertIn("pack.yaml old_name: observed=2 base=1 listed=2; a new finding is not allowed", result.stdout)
        self.assertNotIn(PACK_NAME, result.stdout.lower())

    def test_an_unchanged_count_against_the_base_passes(self):
        budget = '{"pack.yaml": {"old_name": 2}}\n'
        result = self.run_check({"pack.yaml": f"pack: {PACK_NAME}\nnote: changed\n"}, budget,
                                base_files={"pack.yaml": f"pack: {PACK_NAME}\n"})
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("pack.yaml old_name: observed=1 listed=2; lower the budget", result.stdout)

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
            env = {key: value for key, value in os.environ.items() if not key.startswith("GITHUB_")}
            return subprocess.run(
                [sys.executable, "-I", str(SCRIPT), "--branch", branch],
                cwd=root, capture_output=True, text=True, env=env,
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
