"""Boot a disposable Ubuntu outer worker with its own verified disk and NoCloud seed."""

import argparse
from functools import partial
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

IMAGE = "https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"
SHA256 = "04e8f2461a16a44e78a370284471f29616cdd9baf1893df25807b71f985b6c94"


def launch(workdir, machine_id, bootstrap_bytes, *, acquire_image, start_qemu, kubevirt=False):
    if not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", machine_id):
        raise ValueError("Expected a DNS host label for the worker")
    disk = acquire_image(IMAGE, SHA256)
    renderer = os.environ.get("REZONO_WORKER_RENDERER", "rezono-worker-render")
    args = [renderer, "-format", "cloud-init", "-machine", machine_id]
    if kubevirt:
        args.append("-kubevirt")
    workdir = Path(workdir).resolve()
    archive = shutil.which("bsdtar") or (shutil.which("tar.exe") if os.name == "nt" else None)
    if not archive:
        raise RuntimeError("Install libarchive bsdtar to create the NoCloud seed")
    seed = workdir / "cidata.iso"
    with tempfile.TemporaryDirectory(dir=workdir) as directory:
        with (Path(directory) / "user-data").open("xb") as output:
            subprocess.run(args, input=bootstrap_bytes, stdout=output, check=True)
        (Path(directory) / "meta-data").write_text(
            json.dumps({"instance-id": machine_id, "local-hostname": machine_id}), encoding="utf-8"
        )
        # A private file descriptor carries the archive; bootstrap data never enters arguments.
        fd = os.open(seed, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as image:
            subprocess.run([archive, "-cf", "-", "--format", "iso9660", "--options",
                            "iso9660:volume-id=cidata", "-C", directory, "meta-data", "user-data"],
                           stdout=image, check=True)
    return start_qemu([
        "qemu-system-x86_64", "-machine", "q35,accel=kvm", "-cpu", "host", "-m", "7G", "-smp", "3",
        "-display", "none", "-monitor", "none", "-no-reboot", "-serial", f"file:{workdir / 'serial.log'}",
        "-drive", f"file={disk},if=virtio,format=qcow2", "-cdrom", str(seed),
        "-netdev", "user,id=net", "-device", "virtio-net-pci,netdev=net",
    ])


def verified_image(workdir, url, digest):
    disk = workdir / "ubuntu.qcow2"
    with disk.open("xb") as target:
        subprocess.run(["curl", "--fail", "--silent", "--show-error", "--location",
                        "--proto", "=https", "--proto-redir", "=https",
                        "--retry", "2", "--max-time", "180", url], stdout=target, check=True)
    with disk.open("rb") as source:
        if hashlib.file_digest(source, "sha256").hexdigest() != digest:
            raise ValueError("Ubuntu image SHA-256 mismatch")
    subprocess.run(["qemu-img", "resize", "-f", "qcow2", str(disk), "20G"], check=True)
    return disk


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workdir", type=Path)
    parser.add_argument("machine")
    parser.add_argument("--kubevirt", action="store_true")
    args = parser.parse_args()

    launch(args.workdir, args.machine, sys.stdin.buffer.read(), acquire_image=partial(verified_image, args.workdir),
           start_qemu=lambda argv: os.execvp(argv[0], argv), kubevirt=args.kubevirt)


if __name__ == "__main__":
    main()
