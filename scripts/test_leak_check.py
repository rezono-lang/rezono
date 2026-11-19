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


if __name__ == "__main__":
    unittest.main()
