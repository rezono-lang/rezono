"""Exercise the manual Ubuntu trial through its Bash argument boundary."""

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


WORKFLOW = Path(__file__).resolve().parents[2] / ".github/workflows/ubuntu-worker.yml"


def test_ubuntu_trial_dispatch(tmp_path):
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    events = workflow["on"]
    assert set(events) == {"workflow_dispatch"}
    choice = events["workflow_dispatch"]["inputs"]["trial"]
    assert choice["type"] == "choice" and choice["required"] == "true"
    assert choice["options"] == ["registration", "kubevirt"]
    assert workflow["permissions"] == {"contents": "read"}

    job, = workflow["jobs"].values()
    assert set(job["if"].split(" && ")) == {
        "github.repository == 'rezono-lang/rezono'", "github.ref == 'refs/heads/main'", "github.actor == 'vdo89'",
    }
    assert job["runs-on"] == "ubuntu-24.04" and job["timeout-minutes"] == "40"
    checkout, trial = job["steps"]
    assert re.fullmatch("actions/checkout@[0-9a-f]{40}", checkout["uses"])
    assert checkout["with"] == {"persist-credentials": "false", "ref": "${{ github.sha }}"}
    assert trial["shell"] == "bash" and trial["env"] == {"TRIAL": "${{ inputs.trial }}"}
    assert "${{" not in trial["run"]

    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash is required to exercise the trial command")
    probe = tmp_path / "run/probes/worker-join/trial.sh"
    probe.parent.mkdir(parents=True)
    probe.write_text('printf "%s\\n" "$@" > args.txt\n', encoding="ascii")
    received = tmp_path / "args.txt"
    for mode, expected in [
        ("registration", ["--ubuntu"]), ("kubevirt", ["--ubuntu", "--kubevirt"]),
        ("", None), ("registration --kubevirt", None),
    ]:
        received.unlink(missing_ok=True)
        result = subprocess.run([bash, "-c", trial["run"]], cwd=tmp_path, env={**os.environ, "TRIAL": mode})
        if expected is None:
            assert result.returncode != 0 and not received.exists()
        else:
            assert result.returncode == 0
            assert received.read_text(encoding="ascii").splitlines() == expected
