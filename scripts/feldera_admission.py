"""Require a successful live comparison for the current Feldera-changing source revision."""

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import urlencode
import zipfile

# Import only from the trusted base checkout used by the policy workflow.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "compiler" / "ci"))
from verify_feldera_run import verify

ORACLE = ".github/workflows/feldera-oracle.yml"
POLICY = ".github/workflows/red-policy.yml"
STEP = "Require live Feldera evidence for backend changes"
PUSH_HEADER = (
    b"name: Live Feldera oracle\n\non:\n  push:\n    branches: [main]\n  workflow_dispatch:\n\n"
)
NIGHTLY_HEADER = re.compile(
    rb"name: Live Feldera oracle\n\non:\n  schedule:\n    - cron: (['\"])"
    rb"[0-5]?[0-9] (?:[01]?[0-9]|2[0-3]) \* \* \*\1\n"
    rb"  workflow_dispatch:\n\nconcurrency:\n  group: feldera-oracle-\$\{\{ github\.ref \}\}\n"
    rb"  cancel-in-progress: false\n\n"
)
ORIGINAL = {
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
}
BACKEND = {f"compiler/rezono_compiler/{name}.py" for name in
           ("calc_sql", "emit", "rules_split", "rules_sql", "seal", "sqltext")} | {"udf/udf.rs", "udf/udf.toml"}
HARNESS = {node.split("::", 1)[0] for node in ORIGINAL} | {
    ORACLE, "examples/rules_support.py", "examples/support.py", "examples/test_examples.py",
    "compiler/tests/rulegen.py", "compiler/tests/calcgen.py", "compiler/tests/calcsupport.py",
    "compiler/tests/support.py",
}

RUNNER = Path(__file__).resolve().parents[1] / "compiler" / "ci" / "run_feldera_oracle.sh"


def selected_files(source):
    # The live runner selects callers by repository-relative pytest node ID.
    return set(re.findall(r"^\s*([\w./-]+\.py)::[^\s]+\s*$", source, re.MULTILINE))


def relevant(path, selected=()):
    return (path in BACKEND or path in HARNESS or path in selected or
            (path.startswith(("compiler/ci/", "compiler/tests/", "compiler/rezono_compiler/", "examples/"))
             and "feldera" in Path(path).stem.lower() and Path(path).suffix in {".py", ".sh", ".sql"}))


def changed(base, head):
    # No rename detection: both old and new names must be checked, including deletions.
    data = subprocess.check_output(["git", "diff", "--no-renames", "--name-only", "-z", base, head, "--"])
    return [p.decode("utf-8", "surrogateescape") for p in data.split(b"\0") if p]


def oracle_blob(revision):
    entry = subprocess.check_output(["git", "ls-tree", "-z", revision, "--", ORACLE])
    ordinary_file = re.fullmatch(rb"100644 blob ([0-9a-f]+)\t" + re.escape(ORACLE.encode("ascii")) + rb"\0", entry)
    if ordinary_file:
        return subprocess.check_output(["git", "cat-file", "blob", ordinary_file[1].decode("ascii")])
    return b""


def only_install_nightly_schedule(base, head):
    before = oracle_blob(base)
    if not before.startswith(PUSH_HEADER + b"permissions:\n"):
        return False
    after = oracle_blob(head)
    header = NIGHTLY_HEADER.match(after)
    return bool(header and after[header.end():] == before[len(PUSH_HEADER):])


def api(path, *, post=False, binary=False):
    args = ["gh", "api", "--allow-escape-sequences"]
    if post:
        args.extend(["--method", "POST"])
    data = subprocess.check_output([*args, f"repos/{os.environ['GITHUB_REPOSITORY']}/{path}"])
    return data if binary or not data else json.loads(data)


def records(path, key, **filters):
    page = 1
    while True:
        result = api(path + "?" + urlencode(dict(filters, per_page=100, page=page)))[key]
        yield from result
        if len(result) < 100:
            break
        page += 1


def report_ok(data):
    with zipfile.ZipFile(io.BytesIO(data)) as archive, tempfile.TemporaryDirectory() as folder:
        names = ("collected.txt", "results.xml")
        if any(archive.namelist().count(name) != 1 or archive.getinfo(name).file_size > 8 * 1024**2
               for name in names):
            return False
        selected, report = [Path(folder, name) for name in names]
        for path in (selected, report):
            path.write_bytes(archive.read(path.name))
        return ORIGINAL <= set(selected.read_text(encoding="utf-8").splitlines()) and not verify(selected, report)


def matches(run, head, branch, repo):
    return (run["event"] == "workflow_dispatch" and run["path"] == ORACLE and
            run["status"] == "completed" and run["conclusion"] == "success" and
            run["repository"]["full_name"] == repo and run["head_repository"]["full_name"] == repo and
            run["head_branch"] == branch and run["head_sha"] == head)


def ran_comparison(run):
    jobs = records(f"actions/runs/{run['id']}/attempts/{run['run_attempt']}/jobs", "jobs")
    for job in jobs:
        if job["name"] == "oracle" and job["conclusion"] == "success":
            steps = {step["name"]: step["conclusion"] for step in job["steps"]}
            return (steps.get("Compare compiler and example results with Feldera") == "success" and
                    steps.get("Retain collected cases and test results") == "success")
    return False


def proof(head, branch, owner):
    repo = os.environ["GITHUB_REPOSITORY"]
    if owner != repo:
        return None
    for run in records("actions/workflows/feldera-oracle.yml/runs", "workflow_runs", event="workflow_dispatch",
                       head_sha=head, branch=branch, status="success"):
        if matches(run, head, branch, repo) and ran_comparison(run):
            artifacts = [item for item in records(f"actions/runs/{run['id']}/artifacts", "artifacts")
                         if item["name"] == "feldera-oracle" and not item["expired"]]
            if len(artifacts) == 1 and artifacts[0]["size_in_bytes"] <= 16 * 1024**2:
                data = api(f"actions/artifacts/{artifacts[0]['id']}/zip", binary=True)
                if report_ok(data):
                    return run
    return None


def review(base, head, branch, owner):
    selected = selected_files(RUNNER.read_text(encoding="utf-8"))
    paths = changed(base, head)
    if paths == [ORACLE] and only_install_nightly_schedule(base, head):
        print("The daily schedule and per-ref concurrency change leaves the live comparison unchanged.")
        return True
    if not any(relevant(path, selected) for path in paths):
        print("The change does not affect the Feldera backend or live comparison.")
        return True
    run = proof(head, branch, owner)
    if run:
        print(f"Verified all collected Feldera cases in run {run['id']} at {head}.")
        return True
    print(f"Run the live Feldera workflow on this source branch at {head}; a passing report is required.")
    return False


def resume(event):
    # A policy rejection and an oracle completion may arrive in either order.
    # Recheck only the latest policy job that specifically failed at this gate.
    head = event["head_sha"]
    repo = os.environ["GITHUB_REPOSITORY"]
    if event["head_repository"]["full_name"] != repo:
        return
    branch = event["head_branch"]
    if event["path"] == ORACLE:
        if not matches(event, head, branch, repo):
            return
    elif event["path"] != POLICY or event["event"] != "pull_request_target" or event["conclusion"] != "failure":
        return
    query = urlencode({"state": "open", "base": "main", "head": f"{repo.split('/')[0]}:{branch}"})
    for pr in api("pulls?" + query):
        if pr["head"]["sha"] != head or pr["head"]["repo"]["full_name"] != repo:
            continue
        prefix = f"policy pull_request_target {pr['number']} {head} "
        reviews = (r for r in records("actions/workflows/red-policy.yml/runs", "workflow_runs",
                                      event="pull_request_target", head_sha=head, branch=branch)
                   if r["path"] == POLICY and r["display_title"].startswith(prefix))
        latest = next(reviews, None)
        if not latest or latest["status"] != "completed" or latest["conclusion"] != "failure":
            continue
        jobs = list(records(f"actions/runs/{latest['id']}/jobs", "jobs", filter="latest"))
        job = next((j for j in jobs if j["name"] == "Inspect test evidence" and j["conclusion"] == "failure"), None)
        if not job or not any(s["name"] == STEP and s["conclusion"] == "failure" for s in job["steps"]):
            continue
        run = proof(head, branch, repo)
        if run and run["updated_at"] >= job["started_at"]:
            # A re-run starts after its evidence. A repeat failure cannot loop on the same proof.
            api(f"actions/jobs/{job['id']}/rerun", post=True)
            print(f"Requested policy review for pull request {pr['number']} after oracle run {run['id']}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    check = commands.add_parser("review")
    for arg in ("base", "head", "branch", "owner"):
        check.add_argument(arg)
    commands.add_parser("resume")
    args = parser.parse_args()
    if args.action == "review":
        return int(not review(args.base, args.head, args.branch, args.owner))
    resume(json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))["workflow_run"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
