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
from xml.etree import ElementTree

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "scripts"))
import components as ci


class WorkflowEnvironmentTests(unittest.TestCase):
    def test_python_collection_and_execution_get_the_locked_module_reader(self):
        workflow = ROOT / ".github/workflows"
        jobs = yaml.safe_load((workflow / "ci.yml").read_text(encoding="utf-8"))["jobs"]
        for job, command in (("discover", "scripts/components.py inventory"),
                             ("python", "scripts/components.py run-shard")):
            steps = jobs[job]["steps"]
            environment, = [i for i, step in enumerate(steps)
                            if step.get("uses") == "./.github/workflows/python-environment"]
            execution, = [i for i, step in enumerate(steps) if command in step.get("run", "")]
            self.assertLess(environment, execution, job)

        action = yaml.safe_load((workflow / "python-environment/action.yml").read_text(encoding="utf-8"))
        steps = action["runs"]["steps"]
        runtimes = [i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/setup-node@")]
        self.assertEqual(len(runtimes), 1, "All Python jobs need the language runtime to compile authored packs")
        runtime = steps[runtimes[0]]
        self.assertRegex(runtime["uses"], r"^actions/setup-node@[a-f0-9]{40}$")
        self.assertEqual(runtime["with"]["node-version-file"], ".node-version")
        self.assertEqual(runtime["with"]["cache-dependency-path"], "rezono/package-lock.json")
        installation, = [i for i, step in enumerate(steps)
                         if step.get("working-directory") == "rezono" and step.get("run") == "npm ci"]
        self.assertLess(runtimes[0], installation)
        for step in (runtime, steps[installation]):
            self.assertNotIn("if", step)
            self.assertNotIn("continue-on-error", step)


class SelectorTests(unittest.TestCase):
    def test_shared_and_transitive_inputs(self):
        components = ci.discover_components()
        def selected(*files):
            return {c.folder for c in ci.affected_components(components, list(files))}
        self.assertEqual(selected("run/tests/test_quote.py"), {"run"})
        self.assertEqual(selected("run/dispatch_policy.py"), {"run"})
        self.assertEqual(selected("loop/replay.py"), {"loop", "run"})
        self.assertEqual(selected("loop/tests/test_case.py", "run/tests/test_quote.py"), {"loop", "run"})
        self.assertEqual(selected("k8s-admission/parameter_reader.py"), {"k8s-admission", "loop", "run"})
        for path in ("scripts/components.py", "packs/common/pack.yaml", "contracts/core.yaml",
                     "contracts/python/tests/test_ports.py", "loop/pyproject.toml", "unknown/resource",
                     "loop/rezono_cluster.py", "loop/tests/conftest.py", "loop/tests/wire_fixtures.py",
                     "loop/tests/fixtures/recording.json",
                     "docs/publication/l0.md", "docs/compiler/pack.md", "README.md",
                     "decisions/run-offline-acceptance.md", "publication/tests/test_l0.py"):
            self.assertEqual(selected(path), {c.folder for c in components}, path)

    def test_plugin_package_expansion_preserves_full_coverage(self):
        components = ci.discover_components()
        with tempfile.TemporaryDirectory() as tmp, patch.object(ci, "ROOT", Path(tmp)):
            loop = Path(tmp) / "loop"
            loop.mkdir()
            for layout in ('py-modules = ["rezono_cluster", "replay"]',
                           'packages = ["replay"]', 'py-modules = "replay"', "invalid TOML"):
                with self.subTest(layout=layout):
                    (loop / "pyproject.toml").write_text("[tool.setuptools]\n" + layout, encoding="utf-8")
                    self.assertEqual(ci.affected_components(components, ["loop/replay.py"]), components)

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
    def test_weighted_workers_keep_every_id_in_pytest_order(self):
        items = ["a", "b", "c", "d", "e", "f", "g"]
        groups = ci.weighted_workers(items, 3, {"c": 20, "e": 4, "b": 4}, 1)
        self.assertEqual(groups, [["c"], ["a", "b", "f"], ["d", "e", "g"]])
        self.assertCountEqual((node for group in groups for node in group), items)
        self.assertEqual(ci.weighted_workers(items, 1, {}, 1), [items])

    def test_publication_fixture_is_built_once_and_read_from_isolated_stores(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ("scripts/components.py", ".github/workflows/publication_fixture.py"):
                (root / rel).parent.mkdir(parents=True)
                shutil.copyfile(ROOT / rel, root / rel)
            module = root / ci.FORMS_MODULE
            module.parent.mkdir(parents=True)
            module.write_text(
                "from pathlib import Path\nimport pytest\nfrom rezono_publisher.store import FileStore\n"
                "HERE = Path(__file__).parent\n"
                "@pytest.fixture(scope='module')\n"
                "def world(tmp_path_factory):\n"
                "    if (HERE / 'fail').exists(): raise RuntimeError('publication failed')\n"
                "    with (HERE / 'builds').open('x') as built: built.write('one')\n"
                "    store = FileStore(tmp_path_factory.mktemp('store'), bucket='fixture')\n"
                "    store.put_new('objects/seed', b'fresh')\n"
                "    return store, {'source': str(store.root), 'nested': [3, None]}\n"
                "def read(world, value):\n"
                "    store, manifest = world\n"
                "    assert store.get('objects/seed') == b'fresh' and store.bucket == 'fixture'\n"
                "    assert manifest['nested'] == [3, None]\n"
                "    store.put_new('private', value)\n"
                "    return str(store.root) == manifest['source']\n"
                "def test_a(world): (HERE / 'a-source').write_text(str(read(world, b'first')))\n"
                "def test_b(world): (HERE / 'b-source').write_text(str(read(world, b'second')))\n", encoding="utf-8")
            env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_PLUGINS="rezono_cluster",
                       PYTHONPATH=os.pathsep.join(map(str, (ROOT / "edge/publisher", ROOT / "loop"))))
            plans, reports, receipts = [root / name for name in ("plans", "reports", "receipts")]
            launcher = ("import sys; sys.path.insert(0, 'scripts'); import components\n"
                        "from unittest.mock import patch\n"
                        "with patch.object(components, 'runner_cores', return_value=4): "
                        "raise SystemExit(components.main())")
            def run(*args):
                return subprocess.run([sys.executable, "-c", launcher, *map(str, args)],
                                      env=env, cwd=root, capture_output=True, text=True, timeout=35)
            collected = run("collect-component", "examples", plans)
            self.assertEqual(collected.returncode, 0, collected.stdout + collected.stderr)
            def execute():
                return run("run-shard", "examples", 0, 1, plans, reports, receipts)
            result = execute()
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual((module.parent / "builds").read_text(), "one")
            self.assertEqual(len(list(receipts.rglob("*.jsonl"))), 4)
            self.assertIn("Current publication fixture producer:", result.stdout)
            self.assertIn("Current publication fixture reader:", result.stdout)
            self.assertEqual((module.parent / "a-source").read_text(), "True")
            self.assertEqual((module.parent / "b-source").read_text(), "False")
            original = (plans / "examples/items.json").read_text(encoding="utf-8")
            manifest = json.loads(original)
            try:
                for selection in (manifest["items"][::-1], manifest["items"][1:]):
                    (module.parent / "builds").unlink()
                    (plans / "examples/items.json").write_text(
                        json.dumps(dict(manifest, items=selection)), encoding="utf-8")
                    selected = execute()
                    self.assertEqual(selected.returncode, 0, selected.stdout + selected.stderr)
                    self.assertEqual((module.parent / "b-source").read_text(), str(len(selection) == 1))
                    self.assertEqual((module.parent / "builds").read_text(), "one")
            finally:
                (plans / "examples/items.json").write_text(original, encoding="utf-8")
            (module.parent / "fail").touch()
            failed = execute()
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("producer finished without a fresh publication fixture", failed.stdout + failed.stderr)

    def test_parametrization_skips_and_execution_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            script = root / "scripts/components.py"
            shutil.copyfile(ROOT / "scripts/components.py", script)
            profile = Path(".github/workflows/compiler-duration-profile.json")
            (root / profile.parent).mkdir(parents=True)
            shutil.copyfile(ROOT / profile, root / profile)
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
            (component / "test_cluster.py").write_text(
                "import pytest\n"
                "@pytest.fixture\ndef live_resource(): raise RuntimeError('live fixture executed')\n"
                "@pytest.mark.cluster\n"
                "@pytest.mark.xfail(strict=True)\n"
                "class TestCluster:\n    def test_live(self, live_resource): pass\n"
                "@pytest.mark.parametrize('live', [pytest.param(True, marks=pytest.mark.cluster, id='live'), "
                "pytest.param(False, id='offline')])\n"
                "def test_mode(live): assert not live\n", encoding="utf-8")
            matrix = [{"kind": "python", "folder": "compiler", "shard": n, "total": 2} for n in range(2)]
            env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_PLUGINS="rezono_cluster",
                       PYTHONPATH=str(ROOT / "loop"), PYTHON_MATRIX=json.dumps(matrix))
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
            self.assertEqual(17, len(inventory["items"]))
            self.assertEqual(inventory["cluster"], ["compiler/test_cluster.py::TestCluster::test_live",
                                                    "compiler/test_cluster.py::test_mode[live]"])
            for shard in range(2):
                good("run-shard", "compiler", shard, 2, plans, reports / str(shard), receipts)
            result = good("verify-execution", plans, receipts)
            self.assertIn("inventoried 17, started 17, finished 17, disposable cluster required 2", result)
            cases = {case.get("name"): case for report in reports.rglob("pytest-*.xml")
                     for case in ElementTree.parse(report).iter("testcase")}
            for name in ("test_live", "test_mode[live]"):
                skip = cases[name].find("skipped")
                self.assertEqual(skip.get("type"), "pytest.skip")
                self.assertEqual(skip.get("message"), "Requires the dedicated disposable cluster")
            self.assertIsNone(cases["test_mode[offline]"].find("skipped"))

            skip_journal = next(p for p in (receipts / "compiler").glob("*.jsonl")
                                if '"cluster-skip"' in p.read_text(encoding="utf-8"))
            intact = skip_journal.read_text(encoding="utf-8")
            skip_journal.write_text("".join(row for row in intact.splitlines(keepends=True)
                                            if json.loads(row)[0] != "cluster-skip"), encoding="utf-8")
            self.assertNotEqual(run("verify-execution", plans, receipts).returncode, 0)
            skip_journal.write_text(intact, encoding="utf-8")

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
            (component / "test_states.py").write_text(
                "def test_failure(): assert False\ndef test_fixture(missing_fixture): pass\n", encoding="utf-8")
            good("inventory", plans)
            results = [run("run-shard", "compiler", n, 2, plans, reports / str(n), receipts) for n in range(2)]
            self.assertEqual(sorted(r.returncode for r in results), [0, 1])
            self.assertIn("fixture 'missing_fixture' not found", "".join(result.stdout for result in results))
            self.assertIn("inventoried 17, started 17, finished 17", good("verify-execution", plans, receipts))

            # An ambient or plugin filter cannot quietly shrink the independent inventory.
            env["PYTEST_ADDOPTS"] = "-k test_mode"
            filtered = run("inventory", plans)
            self.assertNotEqual(filtered.returncode, 0)
            self.assertIn("tests deselected during full inventory", filtered.stdout)


if __name__ == "__main__":
    unittest.main()
