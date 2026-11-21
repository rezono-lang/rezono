"""Network-free incident reporting from the recorded main comparison and its controls."""

import json
import os
from pathlib import Path
import subprocess
import sys
import xml.etree.ElementTree as ET

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler" / "ci"))
import feldera
import feldera_incident as incident
from feldera_shards import SHARDS, selection
from verify_feldera_run import junit_key


# Selected cases and the two SQL diagnostics are from main run 44256982993,
# artifact 14407983426. Snippets and tracebacks are omitted from the incident.
CASES = [
    "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[full]",
    "compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives[choice]",
    "compiler/tests/test_bound.py::test_the_check_view_on_feldera_holds_the_rows_past_the_bound",
    "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does[0]",
    "compiler/tests/test_rules_properties.py::test_feldera_runs_generated_programs_as_duckdb_does[1]",
    "examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors[library]",
    "examples/test_feldera.py::test_feldera_accepts_the_sql_and_finds_the_errors[projects]",
    "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[platform]",
    "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[subsidy]",
    "examples/test_platform_incremental_proof.py::test_platform_incremental_delta_and_witnesses_match_batch",
]


def sql_error(line):
    diagnostic = {"start_line_number": line, "start_column": 14, "warning": False, "error_type": "Reserved name",
                  "message": "Table 'interval' has the same name as a predefined function"}
    return "RuntimeError: " + json.dumps({"sql_compilation": {"exit_code": 1, "messages": [diagnostic]}})


def records(failures, cases=CASES, selected=CASES):
    suite = ET.Element("testsuite")
    for name in cases:
        module, test = junit_key(name)
        case = ET.SubElement(suite, "testcase", classname=module, name=test)
        if name in failures:
            ET.SubElement(case, "failure", message=failures[name]).text = "E   " + failures[name]
    return "\n".join(selected), ET.tostring(suite)


RED = records({CASES[7]: sql_error(36), CASES[8]: sql_error(96)})
# Run 44244599001 failed before a comparison. Its two JUnit failure types
# must not establish the beginning of the red series.
INFRA = records({CASES[8]: "AssertionError: split packs are measured by the M2 probe; one pipeline here",
                 CASES[9]: "urllib.error.HTTPError: HTTP Error 400: Bad Request"})


def test_a_confirmed_disagreement_requires_complete_comparison_evidence(tmp_path):
    assert incident.disagreements(*RED) == [junit_key(c)[1] for c in CASES[7:9]]
    assert not incident.disagreements(*INFRA)
    assert not incident.disagreements(*records({}))
    assert not incident.disagreements(*records({CASES[7]: sql_error(36)}, CASES[:-1]))
    assert not incident.disagreements(*records({CASES[7]: sql_error(36)}, CASES + CASES[:1]))
    for message in ("TimeoutError: incomplete file inputs", "ConnectionResetError: unavailable",
                    sql_error(36).replace('"warning": false', '"warning": true'),
                    sql_error(36).replace('"exit_code": 1', '"exit_code": 0')):
        assert not incident.disagreements(*records({CASES[7]: message}))
    with pytest.raises(TimeoutError):
        with feldera.comparing():
            raise TimeoutError("data unavailable")
    # Obtain the marker from real pytest JUnit output for an actual unequal result.
    source = tmp_path / "test_difference.py"
    source.write_text(
        "from feldera import comparing\n\ndef test_difference():\n"
        "    with comparing():\n        assert {'expected'} == {'observed'}\n", encoding="utf-8")
    report = tmp_path / "results.xml"
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(Path(path).resolve()) for path in sys.path),
           "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    run = subprocess.run([sys.executable, "-m", "pytest", "-q", str(source), f"--junitxml={report}"],
                         cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert run.returncode == 1, run.stdout + run.stderr
    message = ET.parse(report).find(".//failure").attrib["message"]
    assert incident.disagreements(*records({CASES[0]: message})) == [junit_key(CASES[0])[1]]


@pytest.mark.parametrize("missing_subsidy_report", [False, True])
def test_classifier_uses_complete_reports_from_the_parallel_comparison(tmp_path, missing_subsidy_report):
    ci = Path(incident.__file__).resolve().parent
    cases = CASES + [
        "examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[platform/tenant-capacity/interface]",
        "compiler/tests/test_boolean_rule_inputs.py::test_native_boolean_rule_inputs",
        "compiler/tests/test_recorded_dates.py::test_independent_date_equality",
        "compiler/tests/test_rules_sql_and_access_guards.py::test_rational_functional_base_fact_bounds_and_invalid_denominator",
        "compiler/tests/test_rules_sql_and_access_guards.py::test_zero_rule_functional_relation_emits_valid_sql_with_empty_state",
        "compiler/tests/test_ordered_rule_scalars_engines.py::test_feldera_orders_typed_values",
        "examples/test_calculation_engine_parity.py::test_feldera_calculations_match_duckdb_and_checker[subsidy]",
    ]
    collected, report = records({CASES[7]: sql_error(36), CASES[8]: sql_error(96)}, cases, cases)
    original = ET.fromstring(report)
    inputs = tmp_path / "shards"
    combined = tmp_path / "combined"
    for shard in SHARDS:
        folder = inputs / f"feldera-shard-1-{shard}"
        folder.mkdir(parents=True)
        nodes = selection(collected.splitlines(), shard)
        (folder / "collection.txt").write_text(collected + "\n", encoding="utf-8")
        (folder / "collected.txt").write_text("\n".join(nodes) + "\n", encoding="utf-8")
        if missing_subsidy_report and shard == "subsidy":
            continue
        selected = set(map(junit_key, nodes))
        suite = ET.Element("testsuite", name=shard)
        suite.extend(case for case in original if (case.get("classname"), case.get("name")) in selected)
        ET.ElementTree(suite).write(folder / "results.xml", encoding="utf-8")

    merged = subprocess.run([sys.executable, str(ci / "feldera_shards.py"), "merge", inputs, combined, "1"],
                            capture_output=True, text=True, timeout=10)
    assert merged.returncode == int(missing_subsidy_report), merged.stderr
    assert (combined / "results.xml").exists() == (not missing_subsidy_report)
    if not missing_subsidy_report:
        verified = subprocess.run(
            [sys.executable, str(ci / "verify_feldera_run.py"), combined / "collected.txt", combined / "results.xml"],
            capture_output=True, text=True, timeout=10,
        )
        assert verified.returncode == 1
        assert verified.stderr.splitlines() == [f"ERROR failure: {case}" for case in CASES[7:9]]
        combined_cases = incident.disagreements(
            (combined / "collected.txt").read_text(encoding="utf-8"),
            (combined / "results.xml").read_bytes(),
        )
        assert combined_cases == [junit_key(case)[1] for case in CASES[7:9]]
    classified = subprocess.run([sys.executable, str(ci / "feldera_incident.py"), "classify", combined],
                                capture_output=True, text=True, check=True, timeout=10)
    assert classified.stdout.strip() == ("confirmed=false" if missing_subsidy_report else "confirmed=true")


class History:
    url = "https://github.com/example/example"
    repo = "example/example"

    def __init__(self):
        self.history = []
        self.results = {}
        self.issues = []
        self.updates = []
        self.reads = []

    def run(self, sha, result, records, **changes):
        repository = {"full_name": self.repo}
        run = {"head_sha": sha, "conclusion": result, "status": "completed", "event": "schedule", "head_branch": "main",
               "path": incident.WORKFLOW, "id": len(self.history) + 1, "repository": repository,
               "head_repository": repository, **changes}
        self.history.insert(0, run)
        self.results[run["id"]] = records
        return run

    def cases(self, run):
        self.reads.append(run["id"])
        return incident.disagreements(*self.results[run["id"]])

    def runs(self):
        return self.history

    def verified_green(self, run):
        return incident.green_evidence(*self.results[run["id"]])

    def open_issue(self, marker):
        return next((issue for issue in self.issues if marker in issue["body"].splitlines()), None)

    def create(self, body):
        self.issues.append({"number": len(self.issues) + 1, "body": body})

    def record(self, number, marker, detail):
        comment = (number, marker, detail)
        if comment not in self.updates:
            self.updates.append(comment)


def test_first_confirmed_main_revision_and_last_green_survive_updates_and_retries():
    hub = History()
    g, a, b, c, d, e = [s * 40 for s in "abcdef"]
    hub.run(g, "success", records({}), event="push")
    hub.run(a, "failure", INFRA)
    hub.run("f" * 40, "success", records({}), event="workflow_dispatch")
    first = hub.run(b, "failure", RED)
    hub.run(c, "timed_out", RED)
    hub.run(c, "success", records({}, CASES[:-1]), event="schedule")
    second = hub.run(d, "failure", RED)
    incident.report(hub, second, [d, c, b, a, g])
    body = hub.issues[0]["body"]
    assert f"First confirmed red main revision: `{b}`" in body
    assert f"rollback target is `{g}`" in body
    assert f"/actions/runs/{first['id']}" in body
    latest = hub.run(e, "failure", RED)
    hub.reads.clear()
    for _ in range(2):
        incident.report(hub, latest, [e, d, c, b, a, g])
    assert len(hub.issues) == len(hub.updates) == 1 and hub.reads == [latest["id"]] * 2
    assert hub.issues[0]["body"] == body and e in hub.updates[0][2]


def test_no_green_revision_and_no_issue_for_infrastructure_dispatch_or_other_refs():
    hub = History()
    commit = "a" * 40
    for result, evidence, extra in [("failure", INFRA, {}), ("timed_out", RED, {}),
                                    ("failure", RED, {"event": "workflow_dispatch"}),
                                    ("failure", RED, {"event": "push"}),
                                    ("failure", RED, {"head_repository": {"full_name": "other/project"}}),
                                    ("failure", RED, {"head_branch": "topic"})]:
        incident.report(hub, hub.run(commit, result, evidence, **extra), [commit])
    assert not hub.issues
    incident.report(hub, hub.run(commit, "failure", RED), [commit])
    assert "No previous green Feldera run on main could be verified" in hub.issues[0]["body"]


def test_only_the_serial_main_reporter_can_write_issues():
    workflow = yaml.load((ROOT / incident.WORKFLOW).read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert workflow["concurrency"] == {"group": "feldera-oracle-${{ github.ref }}", "cancel-in-progress": "false"}
    assert workflow["permissions"] == {"contents": "read"}
    oracle = workflow["jobs"]["oracle"]
    assert oracle["outputs"] == {"disagreement": "${{ steps.classify.outputs.confirmed }}"}
    assert oracle["needs"] == "compare" and oracle["if"] == "${{ !cancelled() }}"
    ids = [step["id"] for step in oracle["steps"] if "id" in step]
    assert ids == ["compare", "classify"]
    classifier = next(step for step in oracle["steps"] if step.get("id") == "classify")
    for guard in ("steps.compare.outcome == 'failure'", "github.event_name == 'schedule'", "github.ref == 'refs/heads/main'"):
        assert guard in classifier["if"]
    assert "classify \"$RUNNER_TEMP/feldera-oracle\"" in classifier["run"]
    job = workflow["jobs"]["report"]
    assert job["needs"] == "oracle" and job["permissions"] == {"actions": "read", "contents": "read", "issues": "write"}
    for guard in ("!cancelled()", "github.event_name == 'schedule'", "github.ref == 'refs/heads/main'",
                  "needs.oracle.outputs.disagreement == 'true'"):
        assert guard in job["if"]


def test_issue_adapter_posts_one_comment_for_a_second_red_run(monkeypatch):
    hub = incident.GitHub("example/example")
    issues, comments = [], []
    bot = {"user": {"login": "github-actions[bot]"}, "author_association": "NONE"}

    def request(path, *, method="GET", body=None, pages=False):
        if method == "GET":
            assert pages
            return [comments if path.startswith("issues/7/comments?") else issues]
        assert method == "POST"
        if path == "issues":
            issues.append({**bot, **body, "number": 7})
            return issues[-1]
        assert path == "issues/7/comments"
        comments.append({**bot, **body})
        return comments[-1]

    monkeypatch.setattr(hub, "api", request)
    history = History()
    g, a, b = [digit * 40 for digit in "012"]
    history.run(g, "success", records({}))
    first = history.run(a, "failure", RED)
    second = history.run(b, "failure", RED)
    monkeypatch.setattr(hub, "runs", history.runs)
    monkeypatch.setattr(hub, "cases", history.cases)
    monkeypatch.setattr(hub, "verified_green", history.verified_green)
    incident.report(hub, first, [a, g])
    incident.report(hub, second, [b, a, g])
    incident.report(hub, second, [b, a, g])
    assert len(issues) == len(comments) == 1
    assert a in issues[0]["body"] and g in issues[0]["body"]
    assert b in comments[0]["body"] and f"/actions/runs/{second['id']}" in comments[0]["body"]


@pytest.mark.parametrize(("comparison", "archive", "verified"), [
    ("success", records({}), True),
    ("skipped", records({}), False),
    ("success", None, False),
    ("success", records({}, CASES[:-1]), False),
])
def test_historical_success_requires_the_exact_attempt_and_a_complete_archive(monkeypatch, comparison, archive, verified):
    hub = incident.GitHub("example/example")

    def request(path, *, pages=False):
        assert pages and path == "actions/runs/37/attempts/3/jobs?per_page=100"
        return [{"jobs": [{"name": "oracle", "conclusion": "success", "steps": [
            {"name": "Compare compiler and example results with Feldera", "conclusion": comparison},
            {"name": "Retain collected cases and test results", "conclusion": "success"},
        ]}]}]

    monkeypatch.setattr(hub, "api", request)
    monkeypatch.setattr(hub, "evidence", lambda run: archive)
    assert hub.verified_green({"id": 37, "run_attempt": 3}) == verified
