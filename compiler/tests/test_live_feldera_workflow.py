"""The live oracle has a post-merge job that can also be dispatched for verification."""

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_live_oracle_workflow_runs_the_compiler_entrypoint():
    path = ROOT / ".github/workflows/feldera-oracle.yml"
    job_file = yaml.load(path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = job_file["on"]
    assert set(events) == {"schedule", "workflow_dispatch"}
    assert events["schedule"] == [{"cron": "17 2 * * *"}]
    assert job_file["concurrency"] == {"group": "feldera-oracle-${{ github.ref }}", "cancel-in-progress": "false"}
    entry = "bash compiler/ci/run_feldera_oracle.sh"
    jobs = [job for job in job_file["jobs"].values()
            if any(entry in step.get("run", "").splitlines() for step in job["steps"])]
    job, = jobs
    assert job["runs-on"].startswith("ubuntu-")
    assert 0 < int(job["timeout-minutes"]) < 30
    assert job.get("permissions", job_file.get("permissions")) == {"contents": "read"}
    assert (ROOT / "compiler/ci/run_feldera_oracle.sh").is_file()
    assert job["strategy"]["matrix"]["shard"] == [
        "library", "projects", "platform", "tenant-capacity-interface", "subsidy",
        "compiler-calc", "compiler-bound", "compiler-rules",
    ]
    assert job["strategy"]["fail-fast"] == "false"
    assert any(step.get("env") == {"FELDERA_SHARD": "${{ matrix.shard }}"} for step in job["steps"])
    assert job["steps"][0]["name"] == "Reserve disk space on the disposable runner"
    assert "RUNNER_ENVIRONMENT" in job["steps"][0]["run"]
    setup, = [step["run"] for step in job["steps"] if "--pull" in step.get("run", "")]
    assert setup.index("bash compiler/ci/run_feldera_oracle.sh --pull") < setup.index("python -m venv")
    assert setup.index("python -m venv") < setup.index('wait "$pull_pid"', setup.index("python -m venv"))

    oracle = job_file["jobs"]["oracle"]
    assert oracle["needs"] == "compare"
    publish = [job_name for job_name, item in job_file["jobs"].items()
               for step in item["steps"] if step.get("with", {}).get("name") == "feldera-oracle"]
    assert publish == ["oracle"]
    aggregate, = (step for step in oracle["steps"] if step.get("id") == "compare")
    assert aggregate["name"] == "Compare compiler and example results with Feldera"
    assert "compiler/ci/feldera_shards.py merge" in aggregate["run"]
