"""Boot one pinned Flatcar host and inspect a hardware-accelerated KubeVirt guest."""

import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import re
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
FLATCAR = "https://stable.release.flatcar-linux.net/amd64-usr/4757.2.3"
K0S = "https://github.com/k0sproject/k0s/releases/download/v1.36.6%2Bk0s.0"
KUBEVIRT = "https://github.com/kubevirt/kubevirt/releases/download/v1.9.1"
ARTIFACTS = {
    "host.img.bz2": (
        f"{FLATCAR}/flatcar_production_qemu_image.img.bz2", "sha512",
        "9a9858f45d9c00774f865f38cba856e866f937a49cebaae8a69c4849275dc347edb51499dd145a8a9ac49098ced8ff6f2b66f65242f8b85cb06910c3b9c38e4f",
    ),
    "k0s": (
        f"{K0S}/k0s-v1.36.6%2Bk0s.0-amd64", "sha256",
        "60bac39d4ed8292adb8576a55866389cde4700f9be7d152587e15f8aa67c12fc",
    ),
    "cilium.tgz": (
        "https://helm.cilium.io/cilium-1.20.5.tgz", "sha256",
        "0c7592eb75179ecf46dd3ec22145916f0164c4401214ea15afb5b230b1d11a21",
    ),
    "kubevirt-operator.yaml": (
        f"{KUBEVIRT}/kubevirt-operator.yaml", "sha256",
        "9ac45a436c49d32e6fc21d542bcb7600b970705297b9e6752f3ef9b0a1d292da",
    ),
    "kubevirt-cr.yaml": (
        f"{KUBEVIRT}/kubevirt-cr.yaml", "sha256",
        "43106136dbce3312bdbfdeae612aacafc6c12da518d233f90645b4685d84a2af",
    ),
}


def fetch(directory, item):
    name, (url, algorithm, expected) = item
    path = directory / name
    subprocess.run(["curl", "-fsSL", "--retry", "3", "--max-time", "150",
                    "--output", str(path), url], check=True, timeout=180)
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, algorithm).hexdigest()
    if actual != expected:
        raise ValueError(f"{name} failed {algorithm} verification")
    print(f"verified {name} {algorithm}={actual}", flush=True)


def ignition(port, assets):
    unit = """[Unit]
Description=Verify disposable virtualization host
Wants=network-online.target
After=network-online.target
[Service]
Type=simple
ExecStart=/bin/bash /etc/rezono-probe/guest.sh
[Install]
WantedBy=multi-user.target
"""
    files = []
    contents = {"guest.sh": (HERE / "guest.sh").read_bytes(),
                "k0s.yaml": (HERE / "k0s.yaml").read_bytes(),
                "assets": f"http://10.0.2.2:{port}".encode()}
    checksums = []
    for path in sorted(assets.iterdir()):
        with path.open("rb") as source:
            digest = hashlib.file_digest(source, "sha256").hexdigest()
        checksums.append(f"{digest}  {path.name}\n")
    contents["checksums"] = "".join(checksums).encode()
    for name, data in contents.items():
        uri = "data:;base64," + base64.b64encode(data).decode("ascii")
        files.append({"path": f"/etc/rezono-probe/{name}", "mode": 420,
                      "contents": {"source": uri}})
    return {"ignition": {"version": "3.3.0"}, "storage": {"files": files},
            "systemd": {"units": [{"name": "host-probe.service", "enabled": True, "contents": unit}]}}


def stop_vm(process):
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=8)


def boot(directory, assets):
    observations = []

    class ProbeServer(SimpleHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", 0))
            if self.path != "/observation" or not 0 < length <= 600:
                self.send_error(400)
                return
            event = self.rfile.read(length).decode("ascii")
            if not re.fullmatch(r"[A-Za-z0-9 ./=:+_-]+", event):
                self.send_error(400)
                return
            observations.append(event)
            print(f"HOST-PROBE {event}", flush=True)
            if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
                with open(summary, "a", encoding="utf-8") as output:
                    output.write(f"- Flatcar host: `{event}`\n")
            self.send_response(204)
            self.end_headers()

    handler = partial(ProbeServer, directory=str(assets))
    with ExitStack() as stack:
        server = stack.enter_context(ThreadingHTTPServer(("127.0.0.1", 0), handler))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        stack.callback(server.shutdown)
        config = directory / "host.ign"
        config.write_text(json.dumps(ignition(server.server_port, assets)))
        serial = directory / "serial.log"
        if not os.access("/dev/kvm", os.R_OK | os.W_OK):
            original = subprocess.check_output(["getfacl", "-p", "/dev/kvm"])
            subprocess.run(["sudo", "-n", "setfacl", "-m", f"u:{os.getuid()}:rw", "/dev/kvm"],
                           check=True)
            stack.callback(subprocess.run, ["sudo", "-n", "setfacl", "--restore=-"],
                           input=original, check=True)
        proc = subprocess.Popen([
            "qemu-system-x86_64",
            "-machine", "q35,accel=kvm", "-cpu", "host", "-smp", "4", "-m", "9G",
            "-display", "none", "-monitor", "none", "-no-reboot", "-serial", f"file:{serial}",
            "-drive", f"file={directory / 'host.img'},if=virtio,format=qcow2",
            "-netdev", "user,id=net", "-device", "virtio-net-pci,netdev=net",
            "-fw_cfg", f"name=opt/org.flatcar-linux/config,file={config}",
        ])
        stack.callback(stop_vm, proc)
        deadline = time.monotonic() + 820
        seen = set()
        while time.monotonic() < deadline and proc.poll() is None:
            output = serial.read_text(errors="replace") if serial.exists() else ""
            for line in output.splitlines():
                if "HOST-PROBE" in line and line not in seen:
                    print(line, flush=True)
                    seen.add(line)
            if "end=success" in observations:
                return
            if "end=failure" in observations:
                print(f"Guest failure after {observations}", flush=True)
                raise RuntimeError("Flatcar guest reported failure")
            time.sleep(3)
        if serial.exists():
            lines = serial.read_text(errors="replace").splitlines()
            relevant = [line[:320] for line in lines
                        if any(word in line.lower() for word in ("failed", "error", "panic", "ignition"))]
            print("\n".join(relevant[-18:]), flush=True)
        raise RuntimeError(f"Flatcar probe exited or timed out; QEMU status={proc.poll()}, markers={seen}")


def main():
    with tempfile.TemporaryDirectory(prefix="flatcar-probe-") as tmp:
        directory = Path(tmp)
        assets = directory / "assets"
        assets.mkdir()
        with ThreadPoolExecutor(max_workers=len(ARTIFACTS)) as pool:
            downloads = [pool.submit(fetch, directory, item) for item in ARTIFACTS.items()]
            if not all(shutil.which(tool) for tool in ("qemu-system-x86_64", "qemu-img", "getfacl")):
                apt = ["sudo", "-n", "env", "DEBIAN_FRONTEND=noninteractive", "NEEDRESTART_MODE=a",
                       "apt-get", "-o", "Acquire::Retries=1", "-o", "Acquire::http::Timeout=25",
                       "-o", "DPkg::Lock::Timeout=45"]
                subprocess.run([*apt, "update", "-qq"], check=True, timeout=95)
                subprocess.run([*apt, "install", "-y", "--no-install-recommends",
                                "qemu-system-x86", "qemu-utils", "acl"], check=True, timeout=205)
            for download in downloads:
                download.result()
        for name in ("k0s", "kubevirt-operator.yaml", "kubevirt-cr.yaml"):
            (directory / name).rename(assets / name)
        shutil.copyfile(HERE / "vmi.yaml", assets / "vmi.yaml")
        with (assets / "cilium.yaml").open("wb") as output:
            subprocess.run(["helm", "template", "cilium", str(directory / "cilium.tgz"),
                            "--namespace", "kube-system", "--kube-version", "1.36.6",
                            "--set", "operator.replicas=1", "--set", "hubble.enabled=true",
                            "--set", "hubble.relay.enabled=true",
                            "--set", "ipam.operator.clusterPoolIPv4PodCIDRList[0]=10.244.0.0/16"],
                           check=True, stdout=output, timeout=30)
        with (directory / "host.img").open("wb") as output:
            subprocess.run(["bzip2", "-dc", str(directory / "host.img.bz2")],
                           check=True, stdout=output, timeout=120)
        subprocess.run(["qemu-img", "resize", str(directory / "host.img"), "24G"], check=True)
        boot(directory, assets)


if __name__ == "__main__":
    def expired(signum, frame):
        raise TimeoutError("Disposable host probe reached its lifetime limit")

    for signum in (signal.SIGALRM, signal.SIGTERM):
        signal.signal(signum, expired)
    signal.alarm(960)
    main()
