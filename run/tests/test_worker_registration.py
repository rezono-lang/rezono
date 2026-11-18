"""Exercise the opt-in worker trial and retain its observable success criteria."""

import os
from pathlib import Path
import subprocess

TRIAL = Path(__file__).resolve().parents[1] / "probes" / "worker-join" / "trial.sh"


def test_flatcar_worker_registration(capfd):
    with TRIAL.open(encoding="ascii") as source:
        assert source.readline().strip() == "#!/usr/bin/env bash"
    if os.name == "posix":
        subprocess.run(["bash", "-n", str(TRIAL)], check=True)
    if (os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and os.environ.get("GITHUB_HEAD_REF") == "golf1/planner-run-flatcar-worker-join"):
        with capfd.disabled():
            subprocess.run(["timeout", "--kill-after=15s", "950", "bash", str(TRIAL)], check=True)
