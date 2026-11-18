"""Validate the CI probe lock; the dedicated trial branch also runs it once per PR head."""

import importlib.util
import os
from pathlib import Path
import re
import subprocess
import sys

PROBE = Path(__file__).resolve().parents[1] / "probes" / "flatcar" / "host.py"


def test_flatcar_host_trial(capfd):
    spec = importlib.util.spec_from_file_location("host_probe", PROBE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for url, algorithm, digest in module.ARTIFACTS.values():
        assert url.startswith("https://")
        assert re.fullmatch("[a-f0-9]{%d}" % {"sha256": 64, "sha512": 128}[algorithm], digest)
    if (os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
            and os.environ.get("GITHUB_HEAD_REF") == "golf1/planner-run-flatcar-host-evidence"):
        with capfd.disabled():
            subprocess.run([sys.executable, str(PROBE)], check=True, timeout=1000)
