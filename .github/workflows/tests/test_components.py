"""End-to-end regressions for candidate selection and independent pytest receipts."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import components as ci


class SelectorTests(unittest.TestCase):
    def test_shared_and_transitive_inputs(self):
        components = ci.discover_components()
        def selected(*files):
            return {c.folder for c in ci.affected_components(components, list(files))}
        self.assertEqual(selected("run/tests/test_quote.py"), {"run"})
        self.assertEqual(selected("loop/tests/test_case.py", "run/tests/test_quote.py"), {"loop", "run"})
        self.assertEqual(selected("k8s-admission/parameter_reader.py"), {"k8s-admission", "loop", "run"})
        for path in ("scripts/components.py", "packs/common/pack.yaml", "contracts/core.yaml",
                     "contracts/python/tests/test_ports.py", "loop/pyproject.toml", "unknown/resource"):
            self.assertEqual(selected(path), {c.folder for c in components}, path)

    def test_uses_only_the_candidate_range(self):
        base = subprocess.check_output(["git", "rev-parse", "HEAD^"], cwd=ROOT, text=True).strip()
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
        expected = subprocess.check_output(
            ["git", "diff", "--no-renames", "-z", "--name-only", base, head, "--"], cwd=ROOT
        )
        with patch.dict(os.environ, GITHUB_EVENT_NAME="merge_group",
                        MERGE_GROUP_HEAD_SHA=head, MERGE_GROUP_BASE_SHA=base):
            self.assertEqual(ci._git_changed_files(ROOT, "unrelated", None),
                             [os.fsdecode(p) for p in expected.split(bytes(1)) if p])
            for invalid in ("", "0" * 40, head[:7]):
                with patch.dict(os.environ, MERGE_GROUP_HEAD_SHA=invalid):
                    self.assertIsNone(ci._git_changed_files(ROOT, None, None))
            with patch.dict(os.environ, MERGE_GROUP_BASE_SHA="1" * 40):
                self.assertIsNone(ci._git_changed_files(ROOT, None, None))


class InventoryTests(unittest.TestCase):
    def test_parametrization_skips_and_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            script = root / "scripts/components.py"
            shutil.copyfile(ROOT / "scripts/components.py", script)
            component = root / "compiler"
            component.mkdir()
            (component / "test_numbers.py").write_text(
                "import pytest\n"
                "@pytest.mark.parametrize('n', range(12))\n"
                "def test_number(n): assert n >= 0\n", encoding="utf-8")
            (component / "test_states.py").write_text(
                "import pytest\n"
                "@pytest.mark.skip(reason='offline')\ndef test_skip(): pass\n"
                "@pytest.mark.xfail(strict=True)\ndef test_expected(): assert False\n", encoding="utf-8")
            (component / "test_optional.py").write_text(
                "import pytest\npytest.skip('optional module', allow_module_level=True)\n", encoding="utf-8")
            matrix = [{"kind": "python", "folder": "compiler", "shard": n, "total": 2} for n in range(2)]
            env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTHON_MATRIX=json.dumps(matrix))
            def run(*args):
                return subprocess.run([sys.executable, str(script), *map(str, args)], cwd=root, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            def good(*args):
                proc = run(*args)
                self.assertEqual(proc.returncode, 0, proc.stdout)
                return proc.stdout
            plans, reports, receipts = (root / d for d in ("plans", "reports", "receipts"))
            good("inventory", plans)
            self.assertIn('skipped', (plans / "compiler/collection.xml").read_text(encoding="utf-8"))
            inventory = json.loads((plans / "compiler/items.json").read_text(encoding="utf-8"))
            self.assertEqual(14, len(inventory["items"]))
            for shard in range(2):
                good("run-shard", "compiler", shard, 2, plans, reports / str(shard), receipts)
            result = good("verify-execution", plans, receipts)
            self.assertIn("inventoried 14, started 14, finished 14", result)

            journal = next(p for p in (receipts / "compiler").glob("*.jsonl") if p.stat().st_size)
            original = journal.read_text(encoding="utf-8")
            for changed in ("", original + original):
                journal.write_text(changed, encoding="utf-8")
                self.assertNotEqual(run("verify-execution", plans, receipts).returncode, 0)
            journal.write_text(original, encoding="utf-8")
            # Omit a whole originally inventoried file from the assignment metadata.
            inventory["files"].remove("compiler/test_states.py")
            (plans / "compiler/items.json").write_text(json.dumps(inventory), encoding="utf-8")
            for shard in range(2):
                good("run-shard", "compiler", shard, 2, plans, reports / str(shard), receipts)
            self.assertNotEqual(run("verify-execution", plans, receipts).returncode, 0)

            # A failing assertion is still observed, and always fails the shard.
            (component / "test_states.py").write_text("def test_failure(): assert False\n", encoding="utf-8")
            good("inventory", plans)
            results = [run("run-shard", "compiler", n, 2, plans, reports / str(n), receipts) for n in range(2)]
            self.assertEqual(sorted(r.returncode for r in results), [0, 1])
            self.assertIn("inventoried 13, started 13, finished 13", good("verify-execution", plans, receipts))


if __name__ == "__main__":
    unittest.main()
