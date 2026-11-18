"""Compatibility probes against pinned upstream implementations."""

import base64
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
from urllib.parse import unquote_to_bytes

REVISION = "c23391b08842d8b824e40e1324267f08b923f743"
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def test_flatcar_worker_ignition(tmp_path):
    def git(*args):
        return subprocess.check_output(["git", *args], cwd=tmp_path, text=True).strip()

    git("init", "--quiet")
    git("fetch", "--quiet", "--depth=1", "https://github.com/k0sproject/k0smotron", REVISION)
    assert git("rev-parse", "FETCH_HEAD") == REVISION
    git("checkout", "--quiet", "--detach", REVISION)
    shutil.copyfile(FIXTURES / "worker.go", tmp_path / "worker_probe.go")
    raw = subprocess.check_output(["go", "run", "-mod=readonly", "worker_probe.go"], cwd=tmp_path)
    envelope = json.loads(raw)["ignition"]
    assert envelope["version"].startswith("3.")
    source, = envelope["config"]["merge"]
    metadata, data = source["source"].split(",", 1)
    assert metadata == "data:application/json;base64"
    config = json.loads(base64.b64decode(data, validate=True))
    assert config["ignition"]["version"] == envelope["version"]
    file, = config["storage"]["files"]
    assert (file["path"], file["mode"]) == ("/etc/rezono-probe", 0o644)
    header, body = file["contents"]["source"].split(",", 1)
    value = base64.b64decode(body) if header.endswith(";base64") else unquote_to_bytes(body)
    assert value == b"worker"
    unit, = config["systemd"]["units"]
    assert unit["name"] == "k0s-bootstrap.service" and unit["enabled"]
    assert "/opt/bin/k0s version" in unit["contents"]


def test_runner_virtualization_inventory():
    """Publish measured capabilities in the CI summary without assuming a host OS."""
    cpuinfo = Path("/proc/cpuinfo")
    flags = set(cpuinfo.read_text().split()) if cpuinfo.exists() else set()
    values = {"kernel": platform.release(), "architecture": platform.machine()}
    for flag in ("vmx", "svm"):
        values[flag] = flag in flags
    for device in ("kvm", "net/tun", "vhost-net"):
        path = Path("/dev") / device
        values[device] = path.is_char_device() and os.access(path, os.R_OK | os.W_OK)
    for family in ("intel", "amd"):
        nested = Path(f"/sys/module/kvm_{family}/parameters/nested")
        values[f"nested_{family}"] = nested.read_text().strip() if nested.exists() else "unreported"
    report = json.dumps(values, sort_keys=True)
    print(report)
    if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as output:
            output.write(f"\n### Worker host probe\n\n`{report}`\n")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::notice title=Worker host probe::{report}")
        assert cpuinfo.is_file()
