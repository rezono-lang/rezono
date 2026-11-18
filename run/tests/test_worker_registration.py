"""Check the worker trial script and exercise registration when explicitly enabled."""

import os
from pathlib import Path
import subprocess

import pytest

TRIAL = Path(__file__).resolve().parents[1] / "probes" / "worker-join" / "trial.sh"


def test_worker_registration_script_syntax():
    with TRIAL.open(encoding="ascii") as source:
        assert source.readline().strip() == "#!/usr/bin/env bash"
    subprocess.run(["bash", "-n", str(TRIAL)], check=True)


def test_flatcar_worker_registration(capfd):
    if os.environ.get("REZONO_RUN_WORKER_TRIAL") != "1":
        pytest.skip("Set REZONO_RUN_WORKER_TRIAL=1 on a Linux runner with KVM to run the live worker trial")
    with capfd.disabled():
        subprocess.run(["timeout", "--kill-after=15s", "950", "bash", str(TRIAL)], check=True)
