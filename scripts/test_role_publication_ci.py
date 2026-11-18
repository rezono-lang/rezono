"""Verify the role proof fails closed on uncertain selection or incomplete receipts."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import role_publication_ci as proof


class SelectionTests(unittest.TestCase):
    def test_only_real_readers_and_unknown_paths_require_the_proof(self):
        components = {"admission", "compiler", "examples", "loop", "run", "rezono", "tools/repl", "tools/mcp"}
        for path in ("edge/gate/package-lock.json", "tools/repl/test/publication.accept.ts", "tools/mcp/src/replay.ts",
                     "examples/platform/facts/requests.yaml", "packs/std-explain/labels/en.yaml",
                     "contracts/proof.yaml", "compiler/rezono_compiler/pack.py", "rezono/src/module.ts",
                     "edge/publisher/tests/test_sweep.py", "tools/repl/test/sweep.accept.ts",
                     "viewer/src/lib/canon.ts", "unclassified/source.txt"):
            with self.subTest(path=path):
                self.assertTrue(proof.affected([path], components))
        self.assertFalse(proof.affected(["run/replay.py", "loop/replay.py", "decisions/a-rationale.md"], components))
        self.assertFalse(proof.affected([], components))

    def test_pr_and_merge_group_read_both_sides_and_unknown_range_is_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def git(*args):
                return subprocess.check_output(["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.org",
                                                "-c", "commit.gpgsign=false", *args], cwd=root).decode().strip()

            def write(filename):
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("def test_existing(): pass\n", encoding="utf-8")

            def commit():
                git("add", "-A")
                git("commit", "-qm", "Fixture revision")
                return git("rev-parse", "HEAD")

            git("init", "-q")
            write("run/test_placeholder.py")
            write("tools/mcp/old-source.ts")
            base = commit()
            write("run/replay.py")
            ordinary = commit()
            with patch.object(proof, "ROOT", root):
                self.assertFalse(proof.required("pull_request", base))
                self.assertFalse(proof.required("merge_group", base))
                self.assertTrue(proof.required("pull_request", "missing-base"))
                self.assertFalse(proof.required("push", "missing-base"))
                (root / "tools/mcp/old-source.ts").unlink()
                write("run/new-source.ts")
                commit()
                self.assertTrue(proof.required("pull_request", ordinary))
                self.assertTrue(proof.required("merge_group", ordinary))


class ReceiptTests(unittest.TestCase):
    def test_case_reports_reject_missing_duplicate_skipped_failed_and_errored_cases(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "proof.xml"
            cases = '<testcase name="one"/><testcase name="two"/>'
            for body in (
                '<testcase name="one"/>',
                cases + '<testcase name="one"/>',
                '<testcase name="one"><skipped type="pytest.xfail"/></testcase><testcase name="two"/>',
                '<testcase name="one"><failure/></testcase><testcase name="two"/>',
                '<testcase name="one"><error/></testcase><testcase name="two"/>',
            ):
                with self.subTest(body=body):
                    report.write_text(f"<testsuites><testsuite>{body}</testsuite></testsuites>", encoding="utf-8")
                    with self.assertRaises(ValueError):
                        proof.passing_cases(report, {"one", "two"})
            report.write_text(f"<testsuites><testsuite>{cases}</testsuite></testsuites>", encoding="utf-8")
            proof.passing_cases(report, {"one", "two"})
            report.unlink()
            with self.assertRaises(FileNotFoundError):
                proof.passing_cases(report, {"one", "two"})


if __name__ == "__main__":
    unittest.main()
