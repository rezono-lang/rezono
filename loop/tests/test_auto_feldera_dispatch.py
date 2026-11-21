"""Automatic dispatch of live Feldera evidence and trusted reconciliation resume.

Contract (decisions/live-feldera-ci.md):
- `.github/workflows/dispatch-feldera-evidence.yml` runs strictly from `main`
  (`ref: ${{ github.sha }}`) with `contents: read`, `pull-requests: read`, and
  `actions: write` using only `GITHUB_TOKEN` (no PATs or repository secrets).
- It triggers immediately on `workflow_run` (`workflows: [Review test evidence]`,
  `types: [completed]`) for failed `pull_request_target` runs of
  `.github/workflows/red-policy.yml`, AND periodically on `schedule` (every
  10-15 minutes) plus `workflow_dispatch` so completion recovery never depends
  on a `GITHUB_TOKEN`-dispatched `workflow_dispatch` emitting `workflow_run`.
- `loop/feldera_dispatch.py` (stdlib-only, runnable with `python3 -I`) enforces
  fork-proof, draft-proof, gate-specific, current-head-only, at-most-once
  auto-dispatch per `(head_sha, head_branch)` and delegates proof verification
  to `scripts/feldera_admission.py`'s `proof()` before requesting
  `actions/jobs/{job_id}/rerun` with the `updated_at >= started_at` anti-loop guard.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
DISPATCH_WORKFLOW = ROOT / ".github/workflows/dispatch-feldera-evidence.yml"
ORACLE_WORKFLOW = ROOT / ".github/workflows/feldera-oracle.yml"
POLICY_WORKFLOW = ROOT / ".github/workflows/red-policy.yml"
DISPATCH_SCRIPT = ROOT / "loop/feldera_dispatch.py"

REPO = "example/project"
HEAD = "a" * 40
OLDER_HEAD = "b" * 40
BRANCH = "task/feldera-change"
STEP = "Require live Feldera evidence for backend changes"
ORACLE = ".github/workflows/feldera-oracle.yml"
POLICY = ".github/workflows/red-policy.yml"


def _cron_min_interval_minutes(cron_expr: str) -> int:
    fields = cron_expr.split()
    assert len(fields) == 5, f"expected 5-field cron expression, got {cron_expr!r}"
    minute_field, hour_field, dom, month, dow = fields
    assert (hour_field, dom, month, dow) == ("*", "*", "*", "*"), (
        f"reconciliation schedule must run every hour of every day, got {cron_expr!r}"
    )
    if minute_field.startswith("*/"):
        step = int(minute_field[2:])
        assert 1 <= step <= 60
        return step
    minutes = sorted(int(part) for part in minute_field.split(","))
    assert len(minutes) >= 4 and all(0 <= m < 60 for m in minutes), (
        f"expected 10-15 minute cadence in minute field, got {minute_field!r}"
    )
    return min(b - a for a, b in zip(minutes, [*minutes[1:], minutes[0] + 60]))


def _policy_run(
    pr_number: int,
    head: str,
    *,
    branch: str = BRANCH,
    status: str = "completed",
    conclusion: str = "failure",
) -> dict:
    return {
        "id": 200 + pr_number,
        "path": POLICY,
        "event": "pull_request_target",
        "status": status,
        "conclusion": conclusion,
        "head_sha": head,
        "head_branch": branch,
        "display_title": f"policy pull_request_target {pr_number} {head} false",
    }


def _policy_job(
    job_id: int = 330,
    *,
    conclusion: str = "failure",
    failed_step: str = STEP,
    started_at: str = "2026-01-12T01:00:00Z",
) -> dict:
    return {
        "id": job_id,
        "name": "Inspect test evidence",
        "conclusion": conclusion,
        "started_at": started_at,
        "steps": [{"name": failed_step, "conclusion": "failure"}],
    }


def _oracle_run(
    *,
    head: str = HEAD,
    branch: str = BRANCH,
    repo: str = REPO,
    status: str = "completed",
    conclusion: str | None = "success",
    updated_at: str = "2026-01-12T01:30:00Z",
) -> dict:
    return {
        "id": 710,
        "run_attempt": 1,
        "event": "workflow_dispatch",
        "path": ORACLE,
        "status": status,
        "conclusion": conclusion,
        "head_sha": head,
        "head_branch": branch,
        "repository": {"full_name": repo},
        "head_repository": {"full_name": repo},
        "updated_at": updated_at,
    }


def _pr(
    number: int = 12,
    *,
    head: str = HEAD,
    branch: str = BRANCH,
    repo: str | None = REPO,
    draft: bool = False,
) -> dict:
    return {
        "number": number,
        "draft": draft,
        "head": {
            "sha": head,
            "ref": branch,
            "repo": None if repo is None else {"full_name": repo},
        },
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M3: decisions/live-feldera-ci.md: auto-dispatch feldera-oracle.yml and "
        "reconcile/resume Inspect test evidence via .github/workflows/dispatch-feldera-evidence.yml "
        "and loop/feldera_dispatch.py"
    ),
)
def test_auto_feldera_dispatch_workflow_and_executor_contract():
    # --- 1. Workflow YAML contract & security boundary ---
    assert DISPATCH_WORKFLOW.is_file(), f"missing {DISPATCH_WORKFLOW.relative_to(ROOT)}"
    assert DISPATCH_SCRIPT.is_file(), f"missing {DISPATCH_SCRIPT.relative_to(ROOT)}"

    workflow_text = DISPATCH_WORKFLOW.read_text(encoding="utf-8")
    assert "secrets." not in workflow_text, "dispatch workflow must use default GITHUB_TOKEN, never secrets"

    workflow = yaml.load(workflow_text, Loader=yaml.BaseLoader)
    events = workflow["on"]
    assert set(events) == {"workflow_run", "schedule", "workflow_dispatch"}
    wf_run = events["workflow_run"]
    assert "Review test evidence" in wf_run["workflows"]
    assert wf_run["types"] == ["completed"]
    assert len(events["schedule"]) == 1
    interval = _cron_min_interval_minutes(events["schedule"][0]["cron"])
    assert 5 <= interval <= 15, f"expected 5-15 minute reconciliation schedule, got {interval}m"

    assert workflow["permissions"] == {
        "contents": "read",
        "pull-requests": "read",
        "actions": "write",
    }

    job = workflow["jobs"]["dispatch"]
    assert job["runs-on"].startswith("ubuntu-")
    timeout = int(job["timeout-minutes"])
    assert 1 <= timeout <= min(10, interval)

    condition = job["if"]
    for required_token in (
        "schedule",
        "workflow_dispatch",
        "pull_request_target",
        POLICY,
        "failure",
    ):
        assert required_token in condition, f"job.if missing {required_token!r}: {condition}"

    concurrency = job["concurrency"]
    assert concurrency["cancel-in-progress"] == "false"
    assert "github.event.workflow_run.head_sha" in concurrency["group"]

    steps = job["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert re.fullmatch(r"actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"]["ref"] == "${{ github.sha }}"
    assert checkout["with"]["persist-credentials"] == "false"

    run_step = next(s for s in steps if "loop/feldera_dispatch.py" in s.get("run", ""))
    assert re.search(r"python3?\s+-I\s+loop/feldera_dispatch\.py", run_step["run"])
    assert run_step["env"]["GH_TOKEN"] == "${{ github.token }}"

    # Existing workflows preserve their strict read-only security boundaries.
    oracle_wf = yaml.load(ORACLE_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert oracle_wf["permissions"] == {"contents": "read"}
    policy_wf = yaml.load(POLICY_WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    assert policy_wf["permissions"] == {
        "actions": "read",
        "contents": "read",
        "pull-requests": "read",
    }

    # --- 2. Isolated stdlib-only import under `python -I` ---
    probe = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            (
                "import importlib.util, pathlib; "
                f"spec = importlib.util.spec_from_file_location('fd', {str(DISPATCH_SCRIPT)!r}); "
                "mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod); "
                "assert callable(mod.main)"
            ),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, f"python -I import failed:\n{probe.stderr}"

    from loop import feldera_dispatch as dispatch

    sys.path.insert(0, str(ROOT / "scripts"))
    import feldera_admission as admission

    # --- 3. Safe JSON stdin dispatch via `api()` ---
    with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), \
         patch.object(subprocess, "check_output", return_value=b"") as check_output:
        dispatch.api(
            "actions/workflows/feldera-oracle.yml/dispatches",
            post=True,
            payload={"ref": "@weird/branch"},
        )
        cmd = check_output.call_args.args[0]
        assert cmd[:4] == ["gh", "api", "--allow-escape-sequences", "--method"]
        assert "POST" in cmd and "--input" in cmd and "-" in cmd
        assert cmd[-1] == f"repos/{REPO}/actions/workflows/feldera-oracle.yml/dispatches"
        assert json.loads(check_output.call_args.kwargs["input"].decode("utf-8")) == {
            "ref": "@weird/branch",
        }

    # --- 4. `handle_workflow_run`: happy path, fork/draft/gate/head/dedup guards ---
    def run_event_case(
        *,
        event_overrides: dict | None = None,
        pr_obj: dict | None = None,
        policy_run: dict | None = None,
        policy_job: dict | None = None,
        oracle_runs: list[dict] | None = None,
        proof_run: dict | None = None,
    ) -> list[tuple[str, dict | None]]:
        pr_item = _pr() if pr_obj is None else pr_obj
        p_run = _policy_run(pr_item["number"], HEAD) if policy_run is None else policy_run
        p_job = _policy_job() if policy_job is None else policy_job
        o_runs = [] if oracle_runs is None else oracle_runs
        event = {
            "id": p_run["id"],
            "event": "pull_request_target",
            "path": POLICY,
            "status": "completed",
            "conclusion": "failure",
            "head_sha": HEAD,
            "head_branch": BRANCH,
            "repository": {"full_name": REPO},
            "head_repository": {"full_name": REPO},
        }
        if event_overrides:
            event.update(event_overrides)

        posts: list[tuple[str, dict | None]] = []

        def fake_api(path, *, post=False, payload=None, binary=False):
            if post:
                posts.append((path, payload))
                return b""
            assert path.startswith("pulls?")
            assert "base=main" in path
            return [pr_item]

        def fake_records(path, key, **filters):
            if path == "actions/workflows/red-policy.yml/runs":
                return [p_run]
            if path.endswith("/jobs"):
                return [p_job]
            if path == "actions/workflows/feldera-oracle.yml/runs":
                return o_runs
            raise AssertionError(f"unexpected records({path!r}, {key!r}, {filters!r})")

        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO), \
             patch.object(dispatch, "api", side_effect=fake_api), \
             patch.object(dispatch, "records", side_effect=fake_records), \
             patch.object(admission, "proof", return_value=proof_run):
            dispatch.handle_workflow_run(event)
        return posts

    # Happy path: dispatches feldera-oracle.yml on BRANCH with JSON {"ref": BRANCH}.
    assert run_event_case() == [
        ("actions/workflows/feldera-oracle.yml/dispatches", {"ref": BRANCH}),
    ]

    # Fork-proof (event repo mismatch, PR repo mismatch, deleted fork repo=None).
    assert run_event_case(event_overrides={"head_repository": {"full_name": "fork/project"}}) == []
    assert run_event_case(pr_obj=_pr(repo="fork/project")) == []
    assert run_event_case(pr_obj=_pr(repo=None)) == []

    # Draft-proof: draft PRs do not dispatch.
    assert run_event_case(pr_obj=_pr(draft=True)) == []

    # Gate-specific: red_guard failure must NOT dispatch Feldera.
    assert run_event_case(
        policy_job=_policy_job(failed_step="Review the current head and planner label"),
    ) == []

    # Current-head-only: moved PR head does not dispatch stale SHA.
    assert run_event_case(pr_obj=_pr(head="c" * 40)) == []

    # Event filtering: non-pull_request_target, wrong path, or success conclusion ignored.
    assert run_event_case(event_overrides={"event": "merge_group"}) == []
    assert run_event_case(event_overrides={"path": ".github/workflows/ci.yml"}) == []
    assert run_event_case(event_overrides={"conclusion": "success"}) == []

    # Deduplication: any existing workflow_dispatch run on (HEAD, BRANCH) prevents re-dispatch.
    for status, conclusion in (
        ("queued", None),
        ("in_progress", None),
        ("requested", None),
        ("waiting", None),
        ("pending", None),
        ("completed", "failure"),
        ("completed", "timed_out"),
        ("completed", "action_required"),
        ("completed", "cancelled"),
    ):
        assert run_event_case(
            oracle_runs=[_oracle_run(status=status, conclusion=conclusion)],
        ) == [], f"must not duplicate run with status={status!r}, conclusion={conclusion!r}"

    # An active run on an OLDER SHA of the same branch does NOT block dispatching HEAD.
    assert run_event_case(
        oracle_runs=[_oracle_run(head=OLDER_HEAD, status="in_progress", conclusion=None)],
    ) == [("actions/workflows/feldera-oracle.yml/dispatches", {"ref": BRANCH})]

    # Proof delegation: a completed success run WITHOUT verified admission.proof()
    # must NEITHER rerun Inspect test evidence NOR dispatch a duplicate.
    assert run_event_case(
        oracle_runs=[_oracle_run(status="completed", conclusion="success")],
        proof_run=None,
    ) == []

    # --- 5. `schedule` / `workflow_dispatch` reconciliation sweep via `main()` ---
    pr_ready = _pr(number=21, head=HEAD, branch="task/ready")
    pr_stale_proof = _pr(number=22, head="d" * 40, branch="task/stale")
    pr_needs_dispatch = _pr(number=23, head="e" * 40, branch="task/needs-run")
    pr_green = _pr(number=24, head="f" * 40, branch="task/already-green")
    pr_draft = _pr(number=25, head="1" * 40, branch="task/draft", draft=True)
    pr_fork = _pr(number=26, head="2" * 40, branch="task/fork", repo="fork/project")

    passing_proof = _oracle_run(
        head=pr_ready["head"]["sha"],
        branch="task/ready",
        updated_at="2026-01-12T01:30:00Z",
    )
    stale_proof = _oracle_run(
        head=pr_stale_proof["head"]["sha"],
        branch="task/stale",
        updated_at="2026-01-12T00:59:59Z",
    )

    for event_name in ("schedule", "workflow_dispatch"):
        sweep_posts: list[tuple[str, dict | None]] = []

        def sweep_api(path, *, post=False, payload=None, binary=False):
            if post:
                sweep_posts.append((path, payload))
                return b""
            assert path.startswith("pulls?") and "state=open" in path and "base=main" in path
            if "page=1" in path or "page=" not in path:
                return [pr_ready, pr_stale_proof, pr_needs_dispatch, pr_green, pr_draft, pr_fork]
            return []

        def sweep_records(path, key, **filters):
            if path == "actions/workflows/red-policy.yml/runs":
                sha = filters["head_sha"]
                if sha == pr_ready["head"]["sha"]:
                    return [_policy_run(21, sha, branch="task/ready")]
                if sha == pr_stale_proof["head"]["sha"]:
                    return [_policy_run(22, sha, branch="task/stale")]
                if sha == pr_needs_dispatch["head"]["sha"]:
                    return [_policy_run(23, sha, branch="task/needs-run")]
                if sha == pr_green["head"]["sha"]:
                    return [_policy_run(24, sha, branch="task/already-green", conclusion="success")]
                raise AssertionError(f"unexpected policy lookup for {sha}")
            if path == "actions/runs/221/jobs":
                return [_policy_job(job_id=901, started_at="2026-01-12T01:00:00Z")]
            if path == "actions/runs/222/jobs":
                return [_policy_job(job_id=902, started_at="2026-01-12T01:00:00Z")]
            if path == "actions/runs/223/jobs":
                return [_policy_job(job_id=903, started_at="2026-01-12T01:00:00Z")]
            if path == "actions/workflows/feldera-oracle.yml/runs":
                sha = filters["head_sha"]
                if sha == pr_stale_proof["head"]["sha"]:
                    return [stale_proof]
                if sha == pr_needs_dispatch["head"]["sha"]:
                    return []
                raise AssertionError(f"unexpected oracle runs lookup for {sha}")
            raise AssertionError(f"unexpected records({path!r}, {key!r}, {filters!r})")

        def sweep_proof(head, branch, owner):
            assert owner == REPO
            if head == pr_ready["head"]["sha"] and branch == "task/ready":
                return passing_proof
            if head == pr_stale_proof["head"]["sha"] and branch == "task/stale":
                return stale_proof
            return None

        with patch.dict(os.environ, GITHUB_REPOSITORY=REPO, GITHUB_EVENT_NAME=event_name), \
             patch.object(dispatch, "api", side_effect=sweep_api), \
             patch.object(dispatch, "records", side_effect=sweep_records), \
             patch.object(admission, "proof", side_effect=sweep_proof):
            assert dispatch.main() == 0

        assert sweep_posts == [
            ("actions/jobs/901/rerun", None),
            ("actions/workflows/feldera-oracle.yml/dispatches", {"ref": "task/needs-run"}),
        ], f"{event_name} sweep produced unexpected posts: {sweep_posts}"

    # Verify `main()` also routes GITHUB_EVENT_NAME=workflow_run from GITHUB_EVENT_PATH.
    with tempfile.TemporaryDirectory() as tmp:
        event_file = Path(tmp) / "event.json"
        event_file.write_text(
            json.dumps({"workflow_run": {"event": "push", "path": POLICY, "conclusion": "failure"}}),
            encoding="utf-8",
        )
        with patch.dict(
            os.environ,
            GITHUB_REPOSITORY=REPO,
            GITHUB_EVENT_NAME="workflow_run",
            GITHUB_EVENT_PATH=str(event_file),
        ), patch.object(dispatch, "handle_workflow_run") as handler:
            assert dispatch.main() == 0
            handler.assert_called_once()
