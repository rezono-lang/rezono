"""Measure nested host capacity using the Linux KVM ABI and a disposable empty VM."""

import json
import os
from pathlib import Path
import platform
import subprocess
import sys


def test_guest_hardware_virtualization_capacity(capfd):
    """A capability report is evidence about this runner, not guest readiness."""
    system = platform.system()
    values = {"architecture": platform.machine(), "kernel": platform.release(), "system": system}
    if system == "Linux" and values["architecture"] == "x86_64":
        probe = Path(__file__).resolve().parents[1] / "fixtures" / "kvm_capacity.py"
        command = [sys.executable, str(probe)]
        if os.environ.get("GITHUB_ACTIONS") == "true":
            command = ["sudo", "-n", *command]
        measured = json.loads(subprocess.check_output(command, text=True))
        assert isinstance(measured["create_vm"], bool)
        assert "errno" in measured or {"guest_vmx", "guest_svm"} <= measured.keys()
        values.update(measured)
    report = json.dumps(values, sort_keys=True)
    with capfd.disabled():
        print(f"::notice title=Nested KVM measurement::{report}", flush=True)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"\n### Nested KVM measurement\n\n`{report}`\n")
