"""Exercise native dispatch admission and its event-driven retry without a GitHub token."""

import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
import feldera_admission as gate
from verify_feldera_run import junit_key

REPO = "example/project"
HEAD = "a" * 40
BRANCH = "task/change"
RUN = {"id": 71, "run_attempt": 1, "event": "workflow_dispatch", "path": gate.ORACLE, "status": "completed",
       "conclusion": "success", "head_sha": HEAD, "head_branch": BRANCH, "repository": {"full_name": REPO},
       "head_repository": {"full_name": REPO}, "updated_at": "2026-01-12T01:01:00Z"}


def archive(nodes, reported, outcome=None):
    root = ET.Element("testsuite")
    for node in reported:
        classname, name = junit_key(node)
        case = ET.SubElement(root, "testcase", classname=classname, name=name)
        if outcome:
            ET.SubElement(case, outcome)
    result = io.BytesIO()
    with zipfile.ZipFile(result, "w") as zip_file:
        zip_file.writestr("collected.txt", "\n".join(nodes))
        zip_file.writestr("results.xml", ET.tostring(root))
    return result.getvalue()


class Admission(unittest.TestCase):
    def test_changed_names_cover_both_sides_of_rename(self):
        def git(*args):
            subprocess.run(["git", "-c", "user.name=Fixture", "-c", "user.email=change@example.org", *args],
                           check=True, capture_output=True)
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                git("init", "-q")
                source = Path("compiler/rezono_compiler/rules_sql.py")
                source.parent.mkdir(parents=True)
                source.write_text("# fixture\n", encoding="utf-8")
                git("add", ".")
                git("commit", "-qm", "first")
                git("mv", source.as_posix(), "reader.py")
                git("commit", "-qm", "second")
                self.assertEqual(set(gate.changed("HEAD^", "HEAD")), {source.as_posix(), "reader.py"})
                self.assertTrue(any(map(gate.relevant, gate.changed("HEAD^", "HEAD"))))
            finally:
                os.chdir(previous)
        for name in (gate.ORACLE, "compiler/ci/feldera_incident.py", "compiler/rezono_compiler/feldera_names.py",
                     "examples/feldera_file_input.py", "examples/test_platform_incremental_proof.py"):
            self.assertTrue(gate.relevant(name), name)
        selected = gate.selected_files(gate.RUNNER.read_text(encoding="utf-8") +
                                       "\n  compiler/tests/test_new_proof.py::test_roundtrip\n")
        self.assertTrue({n.split("::")[0] for n in gate.ORIGINAL} <= selected)
        self.assertTrue(gate.relevant("compiler/tests/test_new_proof.py", selected))
        with patch.object(gate, "changed", return_value=["docs/feldera.md", "examples/platform/facts/core.yaml"]), \
             patch.object(gate, "proof", side_effect=AssertionError("unexpected API access")):
            self.assertTrue(gate.review("base", HEAD, BRANCH, REPO))

    def test_only_the_requested_branch_dispatch_proves_this_revision(self):
        self.assertTrue(gate.matches(RUN, HEAD, BRANCH, REPO))
        for change in ({"event": "push"}, {"event": "pull_request"}, {"head_sha": "b" * 40},
                       {"head_branch": "other"}, {"head_repository": {"full_name": "fork/project"}},
                       {"path": ".github/workflows/ci.yml"}, {"status": "in_progress"},
                       {"conclusion": "cancelled"}, {"conclusion": "failure"}):
            self.assertFalse(gate.matches(dict(RUN, **change), HEAD, BRANCH, REPO), change)

    def test_complete_real_case_names_and_junit_agree(self):
        nodes = sorted(gate.ORIGINAL)
        self.assertTrue(gate.report_ok(archive(nodes, nodes)))
        self.assertFalse(gate.report_ok(archive(nodes[1:], nodes[1:])))
        self.assertFalse(gate.report_ok(archive(nodes, nodes[1:])))
        self.assertFalse(gate.report_ok(archive(nodes, [*nodes, nodes[-1]])))
        for outcome in ("skipped", "failure", "error"):
            self.assertFalse(gate.report_ok(archive(nodes, nodes, outcome)))

    def test_only_a_successful_real_job_and_its_artifact_are_admitted(self):
        nodes = sorted(gate.ORIGINAL)
        steps = [{"name": n, "conclusion": "success"} for n in
                 ("Compare compiler and example results with Feldera", "Retain collected cases and test results")]
        artifact = {"id": 38, "name": "feldera-oracle", "expired": False, "size_in_bytes": 1200}
        job = {"name": "oracle", "conclusion": "success", "steps": steps}
        def records(path, key, **filters):
            if key == "workflow_runs":
                self.assertEqual(filters, dict(event="workflow_dispatch", head_sha=HEAD, branch=BRANCH, status="success"))
                return [RUN]
            if key == "jobs":
                self.assertEqual(path, "actions/runs/71/attempts/1/jobs")
                return [job]
            self.assertEqual((path, key), ("actions/runs/71/artifacts", "artifacts"))
            return [artifact]
        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), patch.object(gate, "records", records), \
             patch.object(gate, "api", return_value=archive(nodes, nodes)) as api:
            self.assertFalse(gate.proof(HEAD, BRANCH, "fork/project"))
            self.assertEqual(gate.proof(HEAD, BRANCH, REPO), RUN)
            api.assert_called_once_with("actions/artifacts/38/zip", binary=True)
            artifact["expired"] = True
            self.assertFalse(gate.proof(HEAD, BRANCH, REPO))
            artifact["expired"] = False
            steps[0]["conclusion"] = "skipped"
            self.assertFalse(gate.proof(HEAD, BRANCH, REPO))

    def test_resume_only_failed_gate_on_current_head_after_its_evidence_arrives(self):
        pr = {"number": 4, "head": {"sha": HEAD, "repo": {"full_name": REPO}}}
        policy = {"id": 20, "path": gate.POLICY, "status": "completed", "conclusion": "failure",
                  "display_title": f"policy pull_request_target 4 {HEAD} false"}
        event = dict(RUN, event="pull_request_target", path=gate.POLICY, conclusion="failure")
        job = {"id": 33, "name": "Inspect test evidence", "conclusion": "failure",
               "started_at": "2026-01-12T01:00:00Z", "steps": [{"name": gate.STEP, "conclusion": "failure"}]}
        requests = []
        def api(path, *, post=False):
            if post:
                requests.append(path)
                policy["status"] = "in_progress"
                return
            self.assertIn("base=main", path)
            return [pr]
        def records(path, key, **filters):
            return [policy] if key == "workflow_runs" else [job]
        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), patch.object(gate, "api", api), \
             patch.object(gate, "records", records), patch.object(gate, "proof", return_value=RUN):
            gate.resume(event)
            gate.resume(RUN)
            self.assertEqual(requests, ["actions/jobs/33/rerun"])
            requests.clear()
            policy["status"] = "completed"
            job["started_at"] = "2026-01-12T01:01:01Z"
            gate.resume(event)
            job["started_at"] = "2026-01-12T01:00:00Z"
            job["steps"][0]["name"] = "Review the current head and planner label"
            gate.resume(event)
            job["steps"][0]["name"] = gate.STEP
            pr["head"]["sha"] = "c" * 40
            gate.resume(RUN)
            self.assertEqual(requests, [])

    def test_only_a_daily_scheduler_replacement_can_skip_dispatch(self):
        def git(*args, payload=None):
            return subprocess.check_output(
                ["git", "-c", "user.name=Fixture", "-c", "user.email=change@example.org", *args],
                input=payload,
            ).decode("utf-8").strip()

        header = "name: Live Feldera oracle\n\n"
        push = "on:\n  push:\n    branches: [main]\n  workflow_dispatch:\n\n"
        nightly = ("on:\n  schedule:\n    - cron: '23 2 * * *'\n  workflow_dispatch:\n\n"
                   "concurrency:\n  group: feldera-oracle-${{ github.ref }}\n  cancel-in-progress: false\n\n")
        body = "permissions:\n  contents: read\n\njobs:\n  oracle:\n    steps:\n      - run: compare\n"
        with tempfile.TemporaryDirectory() as tmp:
            previous = Path.cwd()
            try:
                os.chdir(tmp)
                git("init", "-q")
                git("config", "core.filemode", "true")
                flow = Path(gate.ORACLE)
                flow.parent.mkdir(parents=True)

                def put(workflow, mode="100644"):
                    blob = git("hash-object", "-w", "--stdin", payload=workflow.encode("utf-8"))
                    git("update-index", "--add", "--cacheinfo", f"{mode},{blob},{gate.ORACLE}")

                def commit(workflow, mode="100644"):
                    put(workflow, mode)
                    git("commit", "--allow-empty", "-qm", "workflow revision")
                    return git("rev-parse", "HEAD")

                before = commit(header + push + body)
                with patch.object(gate, "proof", return_value=None) as proof:
                    expected = header + nightly + body
                    replacement = commit(expected)
                    self.assertTrue(gate.review(before, replacement, BRANCH, REPO))
                    proof.assert_not_called()
                    for description, workflow in {
                        "minutes outside UTC clock": expected.replace("23 2", "60 2"),
                        "hours outside UTC clock": expected.replace("23 2", "23 24"),
                        "multiple runs per night": expected.replace("23 2", "23 2,3"),
                        "twice repetitive hour": expected.replace("23 2", "23 *"),
                        "additional cron": expected.replace("  workflow_dispatch:", "    - cron: '0 5 * * *'\n  workflow_dispatch:"),
                        "push retained": expected.replace("  schedule:", "  push:\n  schedule:"),
                        "dispatch removed": expected.replace("  workflow_dispatch:\n", ""),
                        "dispatch changed": expected.replace("  workflow_dispatch:", "  workflow_dispatch: {}"),
                        "other concurrency group": expected.replace("github.ref", "github.sha"),
                        "cancels running workflow": expected.replace("false", "true"),
                        "additional concurrency field": expected.replace("false\n", "false\n  extra: true\n"),
                        "job changed": expected.replace("run: compare", "run: changed"),
                        "permissions changed": expected.replace("contents: read", "contents: write"),
                        "name changed": expected.replace("Live Feldera oracle", "Other oracle"),
                        "duplicate top-level trigger": expected + "on:\n  push:\n",
                    }.items():
                        with self.subTest(description=description):
                            self.assertFalse(gate.review(before, commit(workflow), BRANCH, REPO))
                    self.assertFalse(gate.review(before, commit(expected, "100755"), BRANCH, REPO))
                    self.assertFalse(gate.review(before, commit(expected, "120000"), BRANCH, REPO))
                    put(expected)
                    Path("unrelated.txt").write_text("also changed\n", encoding="utf-8")
                    git("add", "unrelated.txt")
                    git("commit", "-qm", "change also adds a path")
                    self.assertFalse(gate.review(before, "HEAD", BRANCH, REPO))
                    self.assertEqual(proof.call_count, 18)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
