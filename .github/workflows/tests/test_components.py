"""End-to-end regressions for candidate selection and independent pytest receipts."""

import ast
import json
import os
from pathlib import Path
import re
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
        for job, command in (("discover", ".build-base/components.py inventory"),
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

    def test_every_node_runtime_reads_the_one_exact_version(self):
        self.assertRegex((ROOT / ".node-version").read_text(encoding="utf-8"), r"^\d+\.\d+\.\d+\n$")
        github = ROOT / ".github"
        found = []
        for path in sorted([*github.glob("workflows/*.yml"), *github.glob("**/action.yml")]):
            document = yaml.safe_load(path.read_text(encoding="utf-8"))
            jobs = {"action": document["runs"]} if path.name == "action.yml" else document.get("jobs", {})
            for name, job in jobs.items():
                steps = job.get("steps", [])
                for i, step in enumerate(steps):
                    if not step.get("uses", "").startswith("actions/setup-node@"):
                        continue
                    where = f"{path.relative_to(ROOT).as_posix()} {name}"
                    found.append(where)
                    self.assertNotIn("node-version", step.get("with", {}), where)
                    self.assertRegex(step["with"].get("node-version-file", ""), r"(^|/)\.node-version$", where)
                    if path.name != "action.yml":
                        self.assertTrue(any(s.get("uses", "").startswith("actions/checkout@") for s in steps[:i]),
                                        f"{where} reads .node-version before a checkout")
        self.assertIn(".github/workflows/release.yml publish", found)
        self.assertIn(".github/actions/release-rehearsal/action.yml action", found)

    def test_the_base_decides_what_runs_and_counts_what_ran(self):
        # A candidate's scripts/components.py, environment action or pytest
        # options must not drop tests from both its inventory and its run.
        jobs = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))["jobs"]
        base = ("${{ github.event.pull_request.base.sha || github.event.merge_group.base_sha "
                "|| github.sha }}")

        steps = jobs["discover"]["steps"]
        runs = [step.get("run", "") for step in steps]
        source, = [i for i, run in enumerate(runs) if "git archive" in run]
        self.assertEqual(steps[source]["env"]["POLICY"], base)
        self.assertIn('git archive "$POLICY" scripts | tar -x -C .build-base --strip-components=1', runs[source])
        for command in ("components.py ci-matrix", "components.py inventory"):
            uses, = [i for i, run in enumerate(runs) if command in run]
            self.assertIn(".build-base/" + command, runs[uses])
            self.assertNotIn("scripts/" + command, runs[uses])
            self.assertLess(source, uses, command)
        inventory, = [run for run in runs if "components.py inventory" in run]
        self.assertLess(inventory.index("unset PYTEST_ADDOPTS PYTEST_PLUGINS"),
                        inventory.index("components.py inventory"))

        steps = jobs["check"]["steps"]
        verify, = [i for i, step in enumerate(steps) if "components.py verify-execution" in step.get("run", "")]
        checkouts = [i for i, step in enumerate(steps) if step.get("uses", "").startswith("actions/checkout@")]
        self.assertEqual(len(checkouts), 1)
        checkout = steps[checkouts[0]]
        self.assertLess(checkouts[0], verify)
        self.assertEqual(checkout["with"]["ref"], base)
        self.assertEqual(checkout["with"]["sparse-checkout"], "scripts")
        self.assertIn("python3 scripts/components.py verify-execution", steps[verify]["run"])

    def test_a_hanging_claim_cleanup_cannot_hold_its_queue_for_hours(self):
        # One concurrency group: without a limit a hung job blocks every later run for up to six hours.
        workflow = yaml.safe_load((ROOT / ".github/workflows/cleanup.yml").read_text(encoding="utf-8"))
        self.assertIsInstance(workflow["concurrency"], str)
        schedule, = workflow[True]["schedule"]  # PyYAML reads the key `on` as True
        minutes = sorted(int(minute) for minute in schedule["cron"].split()[0].split(","))
        interval = min(b - a for a, b in zip(minutes, [*minutes[1:], minutes[0] + 60]))
        self.assertEqual(set(workflow["jobs"]), {"release", "standstill"})
        for name, job in workflow["jobs"].items():
            self.assertIn("timeout-minutes", job, name)
            self.assertLessEqual(job["timeout-minutes"], interval, name)


class SelectorTests(unittest.TestCase):
    def test_shared_and_transitive_inputs(self):
        components = ci.discover_components()
        def selected(*files):
            return {c.folder for c in ci.affected_components(components, list(files))}
        self.assertEqual(selected("run/tests/test_quote.py"), {"run"})
        self.assertEqual(selected("run/dispatch_policy.py"), {"run"})
        self.assertEqual(selected("loop/replay.py"), {"loop", "run", "examples"})
        self.assertEqual(selected("loop/tests/test_case.py", "run/tests/test_quote.py"), {"loop", "run", "examples"})
        self.assertEqual(selected("k8s-admission/parameter_reader.py"), {"k8s-admission", "loop", "run", "examples"})
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


class RepositoryPullRequestSelectionTests(unittest.TestCase):
    """The pull request selection on this repository's own dependency graph."""

    def selected(self, *changed):
        components = ci.discover_components(ROOT, keep_invalid_node=True)
        head = ci.git_output(ROOT, "rev-parse", "HEAD").decode().strip()
        with patch.object(ci, "pull_request_range", return_value=(head, head, list(changed))):
            return {c.folder for c in ci.pull_request_components(components, ROOT, "main")}, components, head

    def test_decision_only_change_selects_no_component_job(self):
        selected, _, _ = self.selected("decisions/a-new-decision.md", "docs/a-new-page.md")
        self.assertEqual(selected, set())

    def test_compiler_change_selects_the_compiler_and_its_dependents_only(self):
        selected, components, head = self.selected("compiler/rezono_compiler/__init__.py")
        folders = {c.folder for c in components}
        declared = ci.declared_dependents(ROOT, head, folders, {})
        self.assertIn("compiler", selected)
        self.assertLessEqual(declared["compiler"], selected)  # edge/publisher declares rezono-compiler
        self.assertLessEqual(set(ci.PR_FILE_CONSUMERS["compiler"]) & folders - ci.PR_DEFERRED_DEPENDENTS, selected)
        self.assertNotIn("tools/mcp", selected)
        # rezono/test/test_message_catalogue.py reads the compiler's sources, also a new one.
        self.assertIn("rezono", self.selected("compiler/rezono_compiler/a_new_module.py")[0])
        self.assertLess(selected, folders)

    def test_loop_and_run_are_deferred_dependents_of_a_pull_request_only(self):
        self.assertEqual(ci.PR_DEFERRED_DEPENDENTS, {"loop", "run"})
        path = "compiler/rezono_compiler/__init__.py"
        selected, components, _ = self.selected(path)
        self.assertTrue(selected.isdisjoint({"loop", "run"}), selected)
        self.assertLessEqual({"loop", "run"}, {c.folder for c in ci.affected_components(components, [path])})
        # The empty set restores them as pull request dependents.
        with patch.object(ci, "PR_DEFERRED_DEPENDENTS", frozenset()):
            restored, _, _ = self.selected(path)
        self.assertEqual(restored, selected | {"loop", "run"})
        # A change to the loop itself still runs it, and run/tests/test_offline_run.py executes loop/replay.py.
        self.assertLessEqual({"loop", "run"}, self.selected("loop/replay.py")[0])
        # A module whose bare stem is a common word in loop and run, but which they do not import or name.
        self.assertTrue(self.selected("compiler/rezono_compiler/emit.py")[0].isdisjoint({"loop", "run"}))

    def test_a_test_file_leaf_keeps_the_readers_of_its_directory(self):
        # compiler/tests/test_domain_free.py scans tests/slip.
        self.assertIn("compiler", self.selected("tests/slip/test_stops_only.py")[0])
        # Under examples/ a leaf test file skips the pack readers of examples/.
        selected = self.selected("examples/a_new_directory/test_a_new_leaf.py")[0]
        self.assertTrue(selected.isdisjoint(set(ci.PACK_READERS) - {"examples"}), selected)

    def test_the_queue_runs_at_least_the_pull_request_closure(self):
        components = ci.discover_components(ROOT, keep_invalid_node=True)
        folders = {c.folder for c in components}
        # Every directory route inside a component, and the files this selection routes.
        routes = [pattern + "probe.yaml" for pattern in ci.SHARED_READERS
                  if pattern.endswith("/") and ci.component_owner(pattern + "probe.yaml", folders)]
        self.assertIn("run/packs/probe.yaml", routes)
        for path in ("loop/replay.py", "loop/tests/test_case.py", "run/dispatch_policy.py",
                     "k8s-admission/parameter_reader.py", "deploy/profiles/edge/forms_issue.py",
                     "run/packs/cleanup-deadline/pack.yaml", "run/packs/dispatch/rules/authorization.dl",
                     "tests/slip/test_stops_only.py", "compiler/rezono_compiler/emit.py", *routes):
            selected, components, _ = self.selected(path)
            self.assertLessEqual(selected, {c.folder for c in ci.affected_components(components, [path])}, path)
        # A change in examples itself still runs everything in the queue, also together with a loop change.
        for changed in (["examples/subsidy/pack.yaml"], ["examples/test_rules.py"],
                        ["loop/replay.py", "examples/test_rules.py"]):
            _, components, _ = self.selected(*changed)
            self.assertEqual(ci.affected_components(components, changed), components, changed)

    def test_unknown_path_selects_every_component(self):
        selected, components, _ = self.selected("an-unknown-directory/resource.yaml")
        self.assertEqual(selected, {c.folder for c in components})


# A tree with the loop, its consumers and paths outside every component.
LOOP_TREE = {
    "loop/pyproject.toml": '[project]\nname = "rezono-loop"\n[tool.setuptools]\npy-modules = ["rezono_cluster"]\n',
    "loop/rezono_cluster.py": "PLUGIN = 1\n",
    "loop/build_choice.py": "CHOICE = 1\n",
    "loop/tests/test_build_choice.py": "from build_choice import CHOICE\n\ndef test_choice(): assert CHOICE\n",
    "run/pyproject.toml": '[project]\nname = "rezono-run"\n',
    "examples/test_examples.py": "def test_examples(): pass\n",
    "examples/demo/test_demo_reader.py": "def test_demo(): pass\n",
    "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
    "compiler/tests/conftest.py": "FIXTURE = 1\n",
    "downstream/pyproject.toml": '[project]\nname = "downstream"\ndependencies = ["rezono-compiler"]\n',
    "idle/pyproject.toml": '[project]\nname = "idle"\n',
    "build/rules/tasks.dl": ".decl task(id: symbol)\n",
    "scripts/standalone_rule.py": "RULE = 1\n",
    "scripts/rule_caller.py": "import standalone_rule\n",
    "scripts/red_list.py": "SKIPS = 1\n",
}
LOOP_EVERYTHING = {"loop", "run", "examples", "compiler", "downstream", "idle"}


class PullRequestSelectorTests(unittest.TestCase):
    def repository(self, directory, files, selector=True):
        root = Path(directory)
        self.write(root, files)
        (root / "scripts").mkdir(exist_ok=not selector)
        shutil.copyfile(ROOT / "scripts/components.py", root / "scripts/components.py")
        self.git(root, "init", "-q")
        self.git(root, "config", "user.email", "selector@example.org")
        self.git(root, "config", "user.name", "Selector tests")
        base = self.commit(root)
        self.git(root, "update-ref", "refs/remotes/origin/main", base)
        return root, base

    @staticmethod
    def write(root, files):
        for path, content in files.items():
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

    @staticmethod
    def git(root, *args):
        return subprocess.check_output(["git", *args], cwd=root, text=True).strip()

    def commit(self, root):
        self.git(root, "add", ".")
        self.git(root, "commit", "-qm", "Fixture")
        return self.git(root, "rev-parse", "HEAD")

    def matrix_output(self, root, event, base, summary=None):
        head = self.git(root, "rev-parse", "HEAD")
        env = os.environ.copy()
        env.pop("GITHUB_OUTPUT", None)
        env.pop("GITHUB_STEP_SUMMARY", None)
        if summary:
            env["GITHUB_STEP_SUMMARY"] = str(summary)
        env.update(GITHUB_EVENT_NAME=event, GITHUB_BASE_REF="main" if event == "pull_request" else "",
                   GITHUB_EVENT_BEFORE=base, MERGE_GROUP_HEAD_SHA=head, MERGE_GROUP_BASE_SHA=base)
        return subprocess.check_output([sys.executable, str(root / "scripts/components.py"), "ci-matrix"], cwd=root, env=env)

    def matrix(self, root, event, base, summary=None):
        output = self.matrix_output(root, event, base, summary).decode()
        fields = dict(line.split("=", 1) for line in output.splitlines())
        return {item["folder"] for kind in ("python", "node") for item in json.loads(fields[kind])}

    def test_python_dependencies_use_base_and_head_transitively(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {
                "compiler/pyproject.toml": '[project]\nname = "Rezono_Compiler"\n',
                "consumer/pyproject.toml": '[project]\nname = "consumer"\n[project.optional-dependencies]\n'
                                           'test = ["rezono.compiler[api] >= 1; python_version >= \'3.11\'"]\n',
                "downstream/pyproject.toml": '[project]\nname = "downstream"\ndependencies = ["consumer ~= 1.0"]\n',
                "independent/pyproject.toml": '[project]\nname = "independent"\n',
            })
            self.write(root, {"compiler/pyproject.toml": '[project]\nname = "renamed-compiler"\n'})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "consumer", "downstream"})
            everything = {"compiler", "consumer", "downstream", "independent"}
            self.assertEqual(self.matrix(root, "merge_group", base), everything)
            self.assertEqual(self.matrix(root, "push", base), everything)

    def test_node_groups_and_workspace_names(self):
        def node(name, **fields):
            return json.dumps({"name": name, "scripts": {"test": "node --test"}, **fields})
        files = {f"node-{name}/package.json": node(name) for name in ("runtime", "optional", "peer", "development", "idle")}
        files.update({
            "package.json": json.dumps({"private": True, "workspaces": {"packages": ["node-*"]}}),
            "node-app/package.json": node("app", dependencies={"runtime": "workspace:^"},
                                          optionalDependencies={"optional": "file:../node-optional"},
                                          peerDependencies={"peer": "^2"},
                                          devDependencies={"alias": "npm:development@^3"}),
        })
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, files)
            components = ci.discover_components(root)
            edges = ci.declared_dependents(root, base, {c.folder for c in components}, {})
            for name in ("runtime", "optional", "peer", "development"):
                self.assertEqual(edges[f"node-{name}"], {"node-app"})
            self.write(root, {"node-peer/index.js": "export const value = 1;\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"node-app", "node-peer"})

    def test_shared_inputs_and_unknown_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {
                "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
                "downstream/pyproject.toml": '[project]\nname = "downstream"\ndependencies = ["rezono-compiler"]\n',
                "idle/pyproject.toml": '[project]\nname = "idle"\n',
                "rezono/package.json": '{"name":"rezono","scripts":{"test":"node --test"}}',
            })
            self.write(root, {"decisions/a-new-decision.md": "# Decision\n", "docs/page.md": "# Page\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), set())
            self.assertEqual(self.matrix(root, "merge_group", base), {"compiler", "downstream", "idle", "rezono"})
            self.write(root, {"docs/compiler/pack.md": "# Pack\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler"})
            self.write(root, {"viewer/src/lib/canon.ts": "export const own = 1;\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "downstream", "rezono"})
            self.write(root, {"unknown/resource.yaml": "unknown: true\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "downstream", "idle", "rezono"})

    def test_connector_source_selects_examples_that_load_it_by_path(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {
                "edge/plugins/connectors/accept.py": "FORMAT = 'first'\n",
                "edge/plugins/connectors/test_accept.py": "def test_accept(): pass\n",
                "examples/test_exports.py": "def test_exports(): pass\n",
                "idle/pyproject.toml": '[project]\nname = "idle"\n',
            })
            self.write(root, {"edge/plugins/connectors/accept.py": "FORMAT = 'second'\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"edge/plugins/connectors", "examples"})

    def test_declared_conformance_test_leaf_preserves_shared_validation_and_native_matrices(self):
        with tempfile.TemporaryDirectory() as directory:
            entry = "compiler/tests/rezono/test_neutral_answer_cases.py"
            probe = "compiler/tests/rezono/neutral-answer-cases.mjs"
            root, base = self.repository(directory, {
                "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
                "checker/pyproject.toml": '[project]\nname = "checker"\n',
                "downstream/pyproject.toml": '[project]\nname = "downstream"\ndependencies = ["rezono-compiler"]\n',
                "rezono/package.json": '{"name":"rezono","scripts":{"test":"node --test"}}',
                entry: 'def test_probe(): assert "neutral-answer-cases.mjs"\n',
                probe: 'export const expected = 1;\n',
            })
            self.write(root, {"unknown/example.yaml": "case: base\n"})
            self.commit(root)
            baseline = {event: self.matrix_output(root, event, base) for event in ("merge_group", "push")}
            (root / "unknown/example.yaml").unlink()
            self.write(root, {
                entry: 'def test_probe(): assert "neutral-answer-cases.mjs".endswith(".mjs")\n',
                probe: 'export const expected = 2;\n',
                "tests/conformance/neutral-case.yaml": "case: example\n",
            })
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"checker", "compiler", "rezono"})
            for event, expected in baseline.items():
                self.assertEqual(self.matrix_output(root, event, base), expected, event)

    def test_cross_component_readers_in_either_tree_keep_full_source_selection(self):
        entry = "compiler/tests/test_neutral_conformance_compiler.py"
        readers = (
            'from compiler.tests.test_neutral_conformance_compiler import collect\n',
            'from runpy import run_path\nrun_path(ROOT / "compiler" / "tests" / "test_neutral_conformance_compiler.py")\n',
        )
        for first, last in ((readers[0], ""), ("", readers[1])):
            with self.subTest(base_reader=bool(first)), tempfile.TemporaryDirectory() as directory:
                root, base = self.repository(directory, {
                    "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
                    "independent/pyproject.toml": '[project]\nname = "independent"\n',
                    "consumer/pyproject.toml": '[project]\nname = "consumer"\n',
                    entry: 'def collect(): return 1\n',
                    "consumer/tests/test_the_input.py": first,
                })
                self.write(root, {entry: 'def collect(): return 2\n', "consumer/tests/test_the_input.py": last})
                self.commit(root)
                self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "consumer", "independent"})

    def test_owned_datalog_selects_the_compiler_inventory(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {
                "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
                "run/tests/test_dispatch.py": "def test_dispatch(): pass\n",
                "idle/pyproject.toml": '[project]\nname = "idle"\n',
            })
            self.write(root, {"run/packs/dispatch/rules/authorization.dl": ".decl grant(item: symbol)\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "run"})
            self.assertEqual(self.matrix(root, "merge_group", base), {"compiler", "run"})

    def test_malformed_manifest_keeps_the_full_matrix(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {
                "compiler/pyproject.toml": '[project]\nname = "rezono-compiler"\n',
                "idle/pyproject.toml": '[project]\nname = "idle"\n',
                "rezono/package.json": '{"name":"rezono","scripts":{"test":"node --test"}}',
            })
            self.write(root, {"rezono/package.json": "[]"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "idle", "rezono"})

    def changed_matrix(self, files, *, tree=None):
        """The pull request matrix for one change on the loop tree, with its step summary."""
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, {**LOOP_TREE, **(tree or {})}, selector=False)
            self.write(root, files)
            self.commit(root)
            summary = Path(directory) / "summary.md"
            selected = self.matrix(root, "pull_request", base, summary)
            return selected, summary.read_text(encoding="utf-8")

    def test_a_test_file_named_only_in_its_component_runs_that_component_alone(self):
        selected, summary = self.changed_matrix({"loop/tests/test_build_choice.py": "def test_choice(): pass\n"})
        self.assertEqual(selected, {"loop"})
        self.assertIn("- `loop`: `loop/tests/test_build_choice.py`", summary)
        # Under examples/ such a test file skips the pack readers of examples/.
        selected, _ = self.changed_matrix({"examples/demo/test_demo_reader.py": "def test_demo(): assert 1\n"})
        self.assertEqual(selected, {"examples"})

    def test_a_test_file_named_elsewhere_keeps_its_component_closure(self):
        reader = {"run/tests/test_replay.py": "from loop.tests.test_build_choice import CHOICE\n"}
        selected, summary = self.changed_matrix({"loop/tests/test_build_choice.py": "def test_choice(): pass\n"},
                                                tree=reader)
        # run is a deferred dependent, but it names the changed test file, so it reads it and runs.
        self.assertEqual(selected, {"loop", "run", "examples"})
        self.assertIn("- `examples`: `loop/tests/test_build_choice.py` through `loop`", summary)
        self.assertIn("- `run`: `loop/tests/test_build_choice.py`, which it names", summary)
        # The loop's own source runs its consumers that are not deferred,
        selected, _ = self.changed_matrix({"loop/build_choice.py": "CHOICE = 2\n"})
        self.assertEqual(selected, {"loop", "examples"})
        # and a deferred one that executes the changed module by name.
        executes = {"run/tests/test_offline.py": 'MODULE = ROOT / "loop" / "build_choice.py"\n'}
        selected, summary = self.changed_matrix({"loop/build_choice.py": "CHOICE = 2\n"}, tree=executes)
        self.assertEqual(selected, {"loop", "run", "examples"})
        self.assertIn("- `run`: `loop/build_choice.py`, which it names", summary)

    def test_a_deferred_dependent_names_a_file_by_import_or_path_not_by_a_bare_word(self):
        tree = {"compiler/rezono_compiler/emit.py": "EMIT = 1\n"}
        change = {"compiler/rezono_compiler/emit.py": "EMIT = 2\n"}
        cases = (
            ("def emit(): pass\n", False),
            ("from rezono_compiler import pack, emit\n", True),
            ("from rezono_compiler import (\n    pack,\n    emit,\n)\n", True),
            ("from rezono_compiler.emit import EMIT\n", True),
            ('MODULE = ROOT / "compiler" / "rezono_compiler" / "emit"\n', True),
            ('MODULE = ROOT / "compiler/rezono_compiler/emit.py"\n', True),
        )
        for text, names in cases:
            with self.subTest(text=text):
                selected, _ = self.changed_matrix(change, tree={**tree, "run/tests/test_reader.py": text})
                self.assertEqual("run" in selected, names, selected)
                self.assertNotIn("loop", selected)

    def test_conftest_runs_the_component_closure(self):
        selected, _ = self.changed_matrix({"compiler/tests/conftest.py": "FIXTURE = 2\n"})
        self.assertEqual(selected, {"compiler", "downstream", "examples"})

    def test_deferred_dependents_run_in_the_merge_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            root, base = self.repository(directory, LOOP_TREE, selector=False)
            self.write(root, {"compiler/source.py": "VALUE = 1\n"})
            self.commit(root)
            self.assertEqual(self.matrix(root, "pull_request", base), {"compiler", "downstream", "examples"})
            self.assertEqual(self.matrix(root, "merge_group", base), LOOP_EVERYTHING)
        self.assertIn("examples", self.changed_matrix({"examples/demo/pack.yaml": "name: demo\n"})[0])
        self.assertEqual(self.changed_matrix({"an-unknown-directory/x.yaml": "x: 1\n"})[0], LOOP_EVERYTHING)

    def test_build_rules_run_the_loop_and_the_compiler(self):
        selected, summary = self.changed_matrix({"build/rules/tasks.dl": ".decl task(id: symbol, at: number)\n"})
        self.assertEqual(selected, {"compiler", "loop"})
        self.assertIn("- `compiler`: `build/rules/tasks.dl`, which it reads", summary)

    def test_paths_outside_components_with_their_readers(self):
        cases = (
            ({"scripts/standalone_rule.py": "RULE = 2\n"}, set()),
            ({".github/workflows/release.yml": "name: release\n"}, set()),
            ({".github/workflows/tests/test_components.py": "# regression\n"}, set()),
            ({"README.md": "# Rezono\n"}, {"examples"}),
            ({"scripts/check-quickstart.sh": "#!/bin/sh\n"}, {"examples"}),
            ({"scripts/red_list.py": "SKIPS = 2\n"}, LOOP_EVERYTHING),
            ({".github/workflows/ci.yml": "name: ci\n"}, LOOP_EVERYTHING),
            ({".github/workflows/python-environment/action.yml": "name: env\n"}, LOOP_EVERYTHING),
            ({"blocked/a-task.txt": "waiting\n"}, LOOP_EVERYTHING),
            ({"an-unknown-directory/resource.yaml": "unknown: true\n"}, LOOP_EVERYTHING),
        )
        for files, expected in cases:
            with self.subTest(files=sorted(files)):
                self.assertEqual(self.changed_matrix(files)[0], expected)
        # A script a component test names, directly or through another script, selects that component only.
        reader = {"run/tests/test_rule.py": "import rule_caller\n"}
        selected, summary = self.changed_matrix({"scripts/standalone_rule.py": "RULE = 3\n"}, tree=reader)
        self.assertEqual(selected, {"run"})
        self.assertIn("- `run`: `scripts/standalone_rule.py`, which it names", summary)
        # A workflow or an action that a component test reads selects that component.
        readers = {
            ".github/workflows/oracle.yml": "name: oracle\n",
            ".github/actions/rehearse/action.yml": "name: rehearse\n",
            "compiler/tests/test_oracle_workflow.py": 'WORKFLOW = ".github/workflows/oracle.yml"\n',
            "run/tests/test_rehearse.py": 'ACTION = ROOT / ".github" / "actions" / "rehearse"\n',
        }
        for files, expected in (({".github/workflows/oracle.yml": "name: oracle 2\n"}, {"compiler"}),
                                ({".github/actions/rehearse/action.yml": "name: rehearse 2\n"}, {"run"})):
            with self.subTest(files=sorted(files)):
                self.assertEqual(self.changed_matrix(files, tree=readers)[0], expected)
        selector =(ROOT / "scripts/components.py").read_text(encoding="utf-8") + "\n# A changed selector.\n"
        selected, summary = self.changed_matrix({"scripts/components.py": selector})
        self.assertEqual(selected, LOOP_EVERYTHING)
        self.assertIn("everything: `scripts/components.py`", summary)

    def test_component_job_scripts_keep_the_full_selection(self):
        """Every script a component job or its environment runs is a full-selection path."""
        workflow = ROOT / ".github/workflows"
        jobs = yaml.safe_load((workflow / "ci.yml").read_text(encoding="utf-8"))["jobs"]
        texts = [json.dumps(jobs[name]) for name in ("python", "node")]
        texts += [(workflow / name).read_text(encoding="utf-8")
                  for name in ("python-environment/action.yml", "disposable-cluster.yml")]
        named = {match for text in texts for match in re.findall(r"scripts/[A-Za-z0-9_.-]+", text)}
        self.assertTrue(named)
        for script in named:
            self.assertTrue(script.startswith(ci.FULL_SELECTION_PATHS) or script in ci.SHARED_READERS, script)
        uses = {step["uses"].removeprefix("./") for job in jobs.values() for step in job.get("steps", [])
                if step.get("uses", "").startswith("./.github/")}
        uses |= {job["uses"].removeprefix("./") for job in jobs.values() if job.get("uses", "").startswith("./")}
        for used in uses:
            self.assertTrue((used + "/").startswith(ci.FULL_SELECTION_PATHS), used)
        for reads in ("compiler-duration-profile.json", "publication_fixture.py"):
            self.assertIn(reads, (ROOT / "scripts/components.py").read_text(encoding="utf-8"))
            self.assertIn(".github/workflows/" + reads, ci.JOB_INPUTS)


SHARED_PATH = re.compile(r"^(?:(?:\.\./|\./)*)(?:docs|decisions|tests/(?:fixtures|conformance)|packs|examples|viewer|edge/plugins|build)(?=/|$)")
JS_STRINGS = re.compile(r"//[^\n]*|/\*[\s\S]*?\*/|(['\x22\x60])((?:\\.|(?!\1)[^\\])*)\1")


def path_expression(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(part.value if isinstance(part, ast.Constant) else "*" for part in node.values)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        right = path_expression(node.right)
        return "/".join(filter(None, (path_expression(node.left), right))) if right is not None else None
    if isinstance(node, ast.Call):
        name = getattr(node.func, "attr", getattr(node.func, "id", ""))
        if name in {"Path", "joinpath"}:
            args = [path_expression(arg) for arg in node.args]
            base = path_expression(node.func.value) if name == "joinpath" else None
            return "/".join(filter(None, [base, *args]))
    return None


def source_paths(text, extension):
    if extension != ".py":
        for match in JS_STRINGS.finditer(text):
            if match[1]:
                path = re.sub(r"\$\{[^{}]*\}", "*", match[2]) if match[1] == "`" else match[2]
                yield path, path.startswith(("../", "./"))
        return
    tree = ast.parse(text)
    contained = {id(node.value) for node in ast.walk(tree)
                 if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)}
    for node in ast.walk(tree):
        if (isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
                or isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "joinpath"):
            contained.update(id(part) for child in ast.iter_child_nodes(node) for part in ast.walk(child))
    for node in ast.walk(tree):
        if id(node) not in contained and (path := path_expression(node)):
            rooted = any(isinstance(part, ast.Name) and part.id in {"HERE", "ROOT", "REPO", "__file__"}
                         for part in ast.walk(node))
            yield path, rooted


QUOTED = r"['\x22]([A-Za-z0-9_.-]+)['\x22]"
GITHUB_PATH = re.compile(rf"\.github/([A-Za-z0-9_./-]+)|['\x22]\.github['\x22]\s*/\s*{QUOTED}\s*/\s*{QUOTED}")


class SharedReaderTests(unittest.TestCase):
    def test_component_files_that_name_a_github_path_are_selected_by_it(self):
        components = ci.discover_components(ROOT, keep_invalid_node=True)
        folders = {c.folder for c in components}
        head = ci.git_output(ROOT, "rev-parse", "HEAD").decode().strip()
        listing = subprocess.check_output(["git", "ls-files", "-z", ".github"], cwd=ROOT).decode()
        tracked = set(filter(None, listing.split("\0")))
        named: dict[str, set[str]] = {}
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
        for relative in filter(None, files):
            owner = ci.component_owner(relative, folders)
            if not owner or not (ROOT / relative).is_file():
                continue
            try:
                text = (ROOT / relative).read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for match in GITHUB_PATH.finditer(text):
                path = ".github/" + (match[1] or f"{match[2]}/{match[3]}").rstrip("/.")
                for target in [path] if path in tracked else [t for t in tracked if t.startswith(path + "/")]:
                    named.setdefault(target, set()).add(owner)
        self.assertIn(".github/workflows/feldera-oracle.yml", named)
        for path, owners in sorted(named.items()):
            with patch.object(ci, "pull_request_range", return_value=(head, head, [path])):
                selected = {c.folder for c in ci.pull_request_components(components, ROOT, "main")}
            self.assertLessEqual(owners, selected, path)

    def test_registered_readers_cover_tracked_test_sources(self):
        components = ci.discover_components(ROOT)
        folders = {c.folder for c in components}
        files = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).split(b"\0")
        paths = {os.fsdecode(path) for path in files if path}
        revision = ci.git_output(ROOT, "rev-parse", "HEAD").decode().strip()
        edges = ci.declared_dependents(ROOT, revision, folders, {})
        for graph in (ci.FILE_CONSUMERS, ci.PR_FILE_CONSUMERS):
            for dependency, consumers in graph.items():
                edges.setdefault(dependency, set()).update(consumers)
        # A directory inside another component, such as a source tree a test globs,
        # is read whether or not the literal is rooted in the test's own syntax.
        directories = {parent.as_posix() for path in paths for parent in Path(path).parents}
        directories = {directory for directory in directories if "/" in directory}
        missing = set()
        observed = set()
        for relative in sorted(paths):
            file = ROOT / relative
            owner = ci.component_owner(relative, folders)
            test_source = (any(part in {"test", "tests", "proof_cases"} for part in Path(relative).parts)
                           or file.name.startswith("test_") or file.name.endswith("_test.py"))
            if not owner or file.suffix not in {".py", ".ts", ".js"} or not (test_source or owner == "rezono"):
                continue
            self.assertTrue(file.resolve().is_relative_to(ROOT), relative)
            if not file.is_file():
                self.fail(f"Tracked test source is missing: {relative}")
            for hint, rooted in source_paths(file.read_text(encoding="utf-8"), file.suffix):
                if not re.fullmatch(r"[a-zA-Z0-9_./*?\[\]-]+", hint):
                    continue
                path = re.sub(r"^(?:\.\./|\./)+", "", hint).rstrip("/")
                inside = path + "/_entry" if path in directories else path
                if (rooted and path in paths or path in directories) and owner != ci.component_owner(inside, folders):
                    provider = ci.component_owner(inside, folders)
                    readers = ci.shared_readers(inside)
                    if readers is not None and not SHARED_PATH.match(hint):
                        if owner in readers or owner in edges.get(provider, set()):
                            observed.add((path, owner))
                        else:
                            missing.add((relative, path, owner))
                        continue
                if (rooted and path in paths or path in directories) and ci.shared_readers(inside) is None:
                    provider = ci.component_owner(inside, folders)
                    if provider:
                        if owner != provider and owner not in edges.get(provider, set()):
                            missing.add((relative, path, owner))
                        else:
                            observed.add((path, owner))
                        continue
                if not SHARED_PATH.match(hint):
                    continue
                if "/" not in path and not rooted:
                    continue  # a role name such as "viewer" is not a repository read
                # Bare paths can also refer to temporary fixture files. Match known
                # repository files (and the explicitly declared future references).
                targets = [path]
                if (ROOT / path).is_dir():
                    targets = [path + "/_entry"]
                    targets.extend(p + ("_entry" if p.endswith("/") else "") for p in ci.SHARED_READERS
                                   if p.startswith(path + "/"))
                for target in targets:
                    readers = ci.shared_readers(target)
                    if readers is None or (not readers and not rooted and not (ROOT / path).exists()):
                        continue
                    if owner not in readers:
                        missing.add((relative, target, owner))
                    else:
                        observed.add((path, owner))
        self.assertEqual(missing, set())
        for citation in (("docs/compiler/pack.md", "compiler"), ("docs/semantics/value-cases.yaml", "rezono"),
                         ("docs/publication/cases", "publication"), ("decisions/publication-case-pins.md", "compiler"),
                         ("decisions/conformance-*.md", "compiler"), ("tests/conformance", "compiler"),
                         ("viewer/src/lib/canon.ts", "rezono"), ("edge/plugins/*/plugin.yaml", "contracts"),
                         ("edge/plugins/connectors/accept.py", "examples"), ("build/schema", "loop")):
            self.assertIn(citation, observed)


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
                                      env=env, cwd=root, capture_output=True, text=True, timeout=120)
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

    def test_a_configured_ignore_cannot_drop_a_file_without_a_blocked_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "scripts").mkdir()
            for name in ("components.py", "red_list.py"):
                shutil.copyfile(ROOT / "scripts" / name, root / "scripts" / name)
            component = root / "probe"
            component.mkdir()
            (component / "test_kept.py").write_text("def test_kept(): pass\n", encoding="utf-8")
            (component / "test_dropped.py").write_text("def test_dropped(): pass\n", encoding="utf-8")
            (component / "test_optional.py").write_text(
                "import pytest\npytest.skip('optional module', allow_module_level=True)\n", encoding="utf-8")
            env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1", PYTEST_PLUGINS="rezono_cluster",
                       PYTHONPATH=str(ROOT / "loop"))
            env.pop("PYTEST_ADDOPTS", None)
            def collect():
                return subprocess.run([sys.executable, str(root / "scripts/components.py"), "collect-component",
                                       "probe", str(root / "plans")], cwd=root, env=env,
                                      stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            self.assertEqual(collect().returncode, 0)
            for option in ("--ignore=probe/test_dropped.py", "--ignore-glob=*/test_drop*.py"):
                (component / "pyproject.toml").write_text(
                    f'[tool.pytest.ini_options]\naddopts = "{option}"\n', encoding="utf-8")
                dropped = collect()
                self.assertNotEqual(dropped.returncode, 0, option)
                self.assertIn("test files without a collected item or a blocked/ record: "
                              "['probe/test_dropped.py']", dropped.stdout)
            (root / "blocked").mkdir()
            (root / "blocked/probe-dropped.txt").write_text(
                "probe/test_dropped.py: needs a capability the probe lacks\n", encoding="utf-8")
            recorded = collect()
            self.assertEqual(recorded.returncode, 0, recorded.stdout)
            inventory = json.loads((root / "plans/probe/items.json").read_text(encoding="utf-8"))
            self.assertEqual(inventory["items"], ["probe/test_kept.py::test_kept"])


if __name__ == "__main__":
    unittest.main()
