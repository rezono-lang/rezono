"""Exercise the pack warnings against real Git history, using only the standard library."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCRIPT = Path(__file__).with_name("pack_warnings.py").resolve()


class PackWarnings(unittest.TestCase):
    def test_pr_changes_use_the_merge_base_and_report_new_literals_only(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)

            def git(*args):
                return subprocess.check_output(
                    ["git", "-c", "user.name=Fixture", "-c", "user.email=lint@example.org", *args],
                    cwd=root, text=True,
                ).strip()

            def write(name, content):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")

            def commit(message):
                git("add", "-A")
                git("commit", "-qm", message)
                return git("rev-parse", "HEAD")

            def check(base, head):
                result = subprocess.run([sys.executable, "-I", str(SCRIPT), base, head],
                                        cwd=root, capture_output=True, text=True, check=True)
                return result.stdout.splitlines()

            git("init", "-q", "-b", "main")
            write("render.py", 'old = "#aabbcc"\nretire = "#fff"\n')
            write("old.css", 'p { color: #345; }\n')
            write("obsolete.js", 'alert("This is no longer used.")\n')
            initial = commit("Initial source")
            git("switch", "-q", "-c", "feature")
            write("render.py", 'old_name = "#aabbcc"\nnew = "#c0ffee"\n'
                  'message = "The delivery has failed."\n'
                  'if row["role"] == "operator": pass\n'
                  'query = "SELECT a FROM the_table WHERE a IS NULL"\n'
                  'key = "message.unknown"\n# role = "ignored"\n'
                  'print("::warning file=input,line=1::machine annotation")\n')
            (root / "obsolete.js").unlink()
            git("mv", "old.css", "renamed.css")
            write("styles,100%.css", 'p { border: 1px solid #def; }\n#abc { display: block; }\n')
            write("deployment.yaml", 'zone: perimeter\nreason: No capacity remains\n')
            write("policy.dl", 'deny(s) :- zone_of(s, z), z = "outer".\n'
                  'side(s) :- edge(s, r), r = "left".\n')
            write("packs/demo/theme.css", 'p { color: #fa0; }\n')
            write("examples/parks/pack.yaml", "id: parks\n")
            write("examples/parks/facts/core.yaml", "role: keeper\n")
            write("examples/parks/render.py", 'raise ValueError("Unknown entry")\n')
            change = commit("Change source and pack data")
            git("switch", "-q", "main")
            write("unrelated.py", 'zone = "main-only"\n')
            divergent_base = commit("Another change on the base")
            warnings = check(divergent_base, change)
            expected = [
                ("deployment.yaml", 1, "zone or role"), ("deployment.yaml", 2, "reader-facing"),
                ("examples/parks/render.py", 1, "reader-facing"), ("policy.dl", 1, "zone or role"),
                ("render.py", 2, "hex colour"), ("render.py", 3, "reader-facing"),
                ("render.py", 4, "zone or role"), ("styles%2C100%25.css", 1, "hex colour"),
            ]
            self.assertEqual(len(warnings), len(expected), warnings)
            for warning, (name, number, kind) in zip(warnings, expected):
                self.assertTrue(warning.startswith(f"::warning file={name},line={number},"))
                self.assertIn(kind, warning)
            self.assertEqual(warnings, check(initial, change))
            self.assertEqual(check(change, change), [])


if __name__ == "__main__":
    unittest.main()
