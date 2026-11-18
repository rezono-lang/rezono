"""Check the actual NoCloud medium attached by the outer Ubuntu worker launcher."""

import os
import re
import shutil
import subprocess
from pathlib import Path
from runpy import run_path
from urllib.parse import urlsplit

import pytest
import yaml


JOIN = Path(__file__).resolve().parents[1] / "probes" / "worker-join"
NOBLE_SHA256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"


def seed_member(image, name):
    # Read the ISO through an independent archive implementation, including Rock Ridge names.
    tar = shutil.which("bsdtar") or (shutil.which("tar.exe") if os.name == "nt" else None)
    if tar:
        args = [tar, "-xOf", str(image), name]
    else:
        args = ["7z", "x", "-so", str(image), name]
    return subprocess.check_output(args, stderr=subprocess.PIPE)


def check_attachment(argv, disk, machine, bootstrap):
    assert Path(argv[0]).name in {"qemu-system-x86_64", "qemu-system-x86_64.exe"}
    drives = [argv[i + 1] for i, arg in enumerate(argv[:-1]) if arg == "-drive"]
    assert any(f"file={disk}" in spec.split(",") for spec in drives)
    media = [Path(field[5:]) for spec in drives for field in spec.split(",") if field.startswith("file=")]
    media += [Path(argv[i + 1]) for i, arg in enumerate(argv[:-1]) if arg == "-cdrom"]
    seeds = []
    for path in media:
        if path != disk:
            with path.open("rb") as stream:
                stream.seek(16 * 2048)
                primary = stream.read(2048)
            if primary[:7] == b"\x01CD001\x01" and primary[40:72].rstrip(b" ").lower() == b"cidata":
                seeds.append(path)
    assert len(seeds) == 1, "Expected one attached NoCloud medium on the outer machine"
    seed = seeds[0]
    assert bootstrap not in " ".join(map(str, argv))
    meta = yaml.safe_load(seed_member(seed, "meta-data"))
    assert meta["instance-id"] == machine and meta["local-hostname"] == machine
    cloud = seed_member(seed, "user-data").decode("utf-8")
    assert cloud.splitlines()[:2] == ["## template: jinja", "#cloud-config"]
    config = yaml.safe_load(cloud)
    token, = [item for item in config["write_files"] if item["path"] == "/etc/k0s-worker-token"]
    assert token["content"].strip() == bootstrap
    mode = token["permissions"]
    assert (mode if isinstance(mode, int) else int(mode, 8)) == 0o600
    commands = "\n".join(cmd if isinstance(cmd, str) else " ".join(cmd) for cmd in config["runcmd"])
    assert "install worker" in commands and "--token-file /etc/k0s-worker-token" in commands
    assert bootstrap not in commands


def test_ubuntu_worker_seed(tmp_path, monkeypatch):
    adapter = JOIN / "ubuntu_worker.py"
    assert adapter.is_file(), "Ubuntu has no outer worker launcher with a NoCloud seed"
    assert re.search(r"(?m)^\s*(?:exec\s+)?python3?\s+[^\n#]*ubuntu_worker\.py\b",
                     (JOIN / "trial.sh").read_text(encoding="utf-8")), "The live trial must use the same launcher"
    assert "provisioner.CloudInitProvisioner{" in (JOIN / "render.go").read_text(encoding="utf-8")
    launch = run_path(str(adapter))["launch"]
    monkeypatch.setenv("GOPROXY", "off")
    monkeypatch.setenv("GOSUMDB", "off")
    disk = tmp_path / "verified-noble.qcow2"
    disk.write_bytes(b"offline image acquisition stand-in")

    for machine in ("outer-one", "outer-two"):
        bootstrap = f"fixture-only-{machine}"
        scratch = tmp_path / machine
        scratch.mkdir()
        calls = []

        def staged_image(url, digest):
            source = urlsplit(url)
            assert source.scheme == "https" and source.hostname == "cloud-images.ubuntu.com"
            assert ("noble" in source.path or "24.04" in source.path) and source.path.endswith("amd64.img")
            assert digest == NOBLE_SHA256
            calls.append("image")
            return disk

        def capture(argv):
            check_attachment(argv, disk, machine, bootstrap)
            calls.append("qemu")

        launch(scratch, machine, bootstrap.encode(), acquire_image=staged_image, start_qemu=capture)
        assert calls == ["image", "qemu"]
