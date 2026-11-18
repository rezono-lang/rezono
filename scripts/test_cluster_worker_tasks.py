"""Exercise cluster routing against real Git objects and pytest node IDs."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cluster_worker_tasks as routing
import fast_check


CLUSTER_TEST = "example/tests/test_network.py"
WORKER_TEST = "loop/tests/test_network.py"
MARKED = """import pytest

@pytest.mark.cluster
def test_network():
    pass
"""
MARKED_ALIAS = "from pytest import mark as m\n\npytestmark = [m.cluster]\ndef test_network():\n    pass\n"
ORDINARY = "def test_network():\n    pass\n"
RED = """@pytest.mark.xfail(strict=True, reason="Requires the fixture")
"""


class ClusterRoutingTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temp)
        self.enterContext(patch.object(routing, "ROOT", self.root))
        self.enterContext(patch.object(fast_check, "ROOT", self.root))
        self.git("init", "-q")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.org")
        self.git("config", "commit.gpgsign", "false")
        self.write("README.md", "Fixture\n")
        self.commit()

    def git(self, *args):
        return routing.git(*args).decode().strip()

    def write(self, path, value):
        file = self.root / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(value, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "-qm", "Fixture revision")
        return self.git("rev-parse", "HEAD")

    def test_ordinary_files_leave_the_cluster_off_and_loop_paths_run_everything(self):
        for path in ("loop/replay.py", "packs/std-loop/pack.yaml", routing.CLUSTER_WORKFLOW, "run/replay.py"):
            with self.subTest(path=path):
                base = self.git("rev-parse", "HEAD")
                self.write(path, "changed\n")
                self.commit()
                expected = "none" if path.startswith("run/") else "suite"
                self.assertEqual(routing.route(set(), diff_base=base), (expected, []))
                self.assertEqual(routing.route(set(), base=base), ("none", []))
        base = self.git("rev-parse", "HEAD")
        self.write(CLUSTER_TEST, '# "@pytest.mark.cluster" in a comment is not a mark\n' + ORDINARY)
        self.commit()
        self.assertEqual(routing.route(set(), diff_base=base), ("none", []))

    def test_added_and_modified_marked_test_runs_full_suite(self):
        base = self.git("rev-parse", "HEAD")
        self.write(CLUSTER_TEST, MARKED_ALIAS)
        modified_base = self.commit()
        self.assertEqual(routing.route(set(), diff_base=base), ("suite", []))
        self.write(CLUSTER_TEST, MARKED_ALIAS.replace("pass", "assert True"))
        head = self.commit()
        self.assertEqual(routing.route(set(), diff_base=modified_base), ("suite", []))
        self.assertEqual(routing.route(set(), diff_base=head), ("none", []))

    def test_deleted_test_and_removed_mark_are_found_in_the_base_tree(self):
        self.write(CLUSTER_TEST, MARKED)
        base = self.commit()
        self.write(CLUSTER_TEST, ORDINARY)
        self.commit()
        self.assertEqual(routing.route(set(), diff_base=base), ("suite", []))
        other = "example/tests/deleted_test.py"
        self.write(other, MARKED)
        base = self.commit()
        (self.root / other).unlink()
        self.commit()
        self.assertEqual(routing.route(set(), diff_base=base), ("suite", []))

    def test_rename_retains_the_old_cluster_side_without_a_head_inventory(self):
        self.write(CLUSTER_TEST, MARKED)
        base = self.commit()
        target = self.root / "example/network_notes.py"
        (self.root / CLUSTER_TEST).rename(target)
        self.commit()
        self.assertEqual(routing.route(set(), diff_base=base), ("suite", []))

    def test_task_routes_from_the_real_inventory_even_when_a_suite_path_changes(self):
        marked_red = MARKED.replace("@pytest.mark.cluster\n", "@pytest.mark.cluster\n" + RED)
        self.write(WORKER_TEST, marked_red)
        base = self.commit()
        self.write(WORKER_TEST, MARKED)
        self.write("loop/replay.py", "changed\n")
        self.commit()
        task = WORKER_TEST + "--test_network"
        inventory = {WORKER_TEST + "::test_network[matching-parameter]"}
        self.assertEqual(routing.route(inventory, worker="task/" + task, base=base, diff_base=base),
                         ("tasks", [task]))
        self.assertEqual(routing.route(inventory, base=base, diff_base=base), ("tasks", [task]))
        self.assertEqual(routing.route(set(), worker="task/" + task, base=base, diff_base=base),
                         ("suite", []))

    def test_head_inventory_routes_a_mark_assigned_by_a_plugin(self):
        base = self.git("rev-parse", "HEAD")
        self.write(CLUSTER_TEST, ORDINARY)
        self.commit()
        self.assertEqual(routing.route({CLUSTER_TEST + "::test_network"}, diff_base=base), ("suite", []))

    def test_diff_base_must_be_an_ancestor_of_the_checked_out_candidate(self):
        fork_point = self.git("rev-parse", "HEAD")
        self.git("switch", "-qc", "separate")
        self.write(CLUSTER_TEST, MARKED)
        separate = self.commit()
        self.git("switch", "-q", "--detach", fork_point)
        self.write("loop/replay.py", "candidate\n")
        self.commit()
        with self.assertRaises(subprocess.CalledProcessError):
            routing.route(set(), diff_base=separate)

    def test_cli_preserves_exact_worker_list_and_encodes_the_full_suite_as_empty_input(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        for filename in ("cluster_worker_tasks.py", "components.py", "fast_check.py", "red_list.py"):
            (scripts / filename).write_bytes(Path(__file__).with_name(filename).read_bytes())
        paths = self.root / "inventory"
        paths.mkdir()
        (paths / "items.json").write_text(json.dumps({"cluster": []}), encoding="utf-8")
        self.write(WORKER_TEST, MARKED.replace("@pytest.mark.cluster\n", "@pytest.mark.cluster\n" + RED))
        base = self.commit()
        self.write("loop/replay.py", "changed\n")
        self.commit()
        command = [sys.executable, str(scripts / "cluster_worker_tasks.py"), str(paths)]
        full = subprocess.check_output([*command, "--diff-base", base], cwd=self.root, text=True)
        old = subprocess.check_output([*command, "--base", base], cwd=self.root, text=True)
        self.assertEqual(full, "mode=suite\ntasks=\n")
        self.assertEqual(old, "mode=none\ntasks=[]\n")
        task = WORKER_TEST + "--test_network"
        (paths / "items.json").write_text(json.dumps({"cluster": [WORKER_TEST + "::test_network"]}), encoding="utf-8")
        exact = subprocess.check_output([*command, "--diff-base", base, "--worker", "task/" + task],
                                        cwd=self.root, text=True)
        self.assertEqual(exact, f"mode=tasks\ntasks={json.dumps([task])}\n")


if __name__ == "__main__":
    unittest.main()
