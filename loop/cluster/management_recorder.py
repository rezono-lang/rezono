"""Shared Kubernetes recorder helpers for live management trials on the disposable cluster."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from ipaddress import ip_address
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
from time import sleep, time_ns
from typing import Any
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
CONTEXT = "kind-rezono-fixture"
CLUSTER_NAME = "rezono-fixture"
NAMESPACE = "rezono-probes"
RECORDER_IMAGE = "docker.io/library/rezono-network-fixture:local"
PROBE_SOURCE = ROOT / "loop" / "cluster" / "network_probe.go"


def run(
    *args: str,
    data: str | None = None,
    limit: int = 30,
    env: dict[str, str] | None = None,
) -> str:
    return subprocess.run(
        args,
        input=data,
        check=True,
        text=True,
        encoding="utf-8",
        stdout=subprocess.PIPE,
        timeout=limit,
        env=env,
    ).stdout


class ManagementCluster:
    """Validate the disposable kind fixture and emit native recorder Jobs in rezono-probes."""

    def __init__(self, env: dict[str, str] | None = None) -> None:
        source = os.environ if env is None else env
        self.run = source["GITHUB_RUN_ID"]
        self.attempt = source["GITHUB_RUN_ATTEMPT"]
        if not all(n.isascii() and n.isdecimal() for n in (self.run, self.attempt)):
            raise ValueError("The management recorder needs the runner's numeric run and attempt")
        self.temp = Path(source["RUNNER_TEMP"]).resolve(strict=True)
        config = Path(source["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
        if not config.is_relative_to(self.temp):
            raise RuntimeError("The management recorder kubeconfig must reside inside RUNNER_TEMP")
        self.kubeconfig = config
        base = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
        if run(*base, "config", "current-context").strip() != CONTEXT:
            raise RuntimeError("The fixture kubeconfig has an unexpected current context")
        server = run(*base, "config", "view", "--minify", "-o", "jsonpath={.clusters[0].cluster.server}").strip()
        hostname = urlsplit(server).hostname
        if not hostname or (hostname != "localhost" and not ip_address(hostname).is_loopback):
            raise RuntimeError("The fixture API server must be runner-local")
        self.server = server
        self.command = [*base, "--context", CONTEXT]
        nodes = self.read("get", "nodes")["items"]
        kind_nodes = run("kind", "get", "nodes", "--name", CLUSTER_NAME).split()
        if len(kind_nodes) != 1 or {node["metadata"]["name"] for node in nodes} != set(kind_nodes):
            raise RuntimeError("The management recorder requires the single pinned local kind node")
        self.node, = kind_nodes
        self._last_tick_us = 0

    def namespaced(self, namespace: str, *args: str) -> list[str]:
        return [*self.command, "-n", namespace, *args]

    def read(self, *args: str, namespace: str | None = None, limit: int = 30) -> dict[str, Any]:
        command = self.namespaced(namespace, *args) if namespace else [*self.command, *args]
        return json.loads(run(*command, "-o", "json", limit=limit))

    def apply(self, manifest: dict[str, Any], limit: int = 30) -> None:
        run(*self.command, "apply", "-f", "-", data=json.dumps(manifest), limit=limit)

    def delete(self, *args: str, namespace: str | None = None, limit: int = 45) -> None:
        command = self.namespaced(namespace, "delete", *args) if namespace else [*self.command, "delete", *args]
        run(*command, "--ignore-not-found", limit=limit)

    def wait(self, *args: str, namespace: str | None = None, limit: int = 90) -> None:
        command = self.namespaced(namespace, "wait", *args) if namespace else [*self.command, "wait", *args]
        run(*command, limit=limit)

    def start_pod_watch(self, namespace: str) -> subprocess.Popen[str]:
        """Start a long-lived `kubectl get pods --watch` stream and fail closed if it exits immediately."""
        watch = subprocess.Popen(
            [*self.namespaced(namespace, "get", "pods", "--watch", "--output-watch-events", "-o", "json"),
             "--request-timeout=0"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        sleep(2)
        if watch.poll() is not None:
            raise RuntimeError(f"The management fence watch ended at once: {watch.stderr.read()}")
        return watch

    def ensure_namespace(self, name: str, labels: dict[str, str] | None = None) -> None:
        metadata: dict[str, Any] = {"name": name}
        if labels:
            metadata["labels"] = labels
        self.apply({"apiVersion": "v1", "kind": "Namespace", "metadata": metadata})

    def image_loaded(self, image: str) -> bool:
        short = image.removeprefix("docker.io/library/")
        listed = run("docker", "exec", self.node, "crictl", "images", "-o", "json", limit=25)
        images = json.loads(listed).get("images", [])
        return any(
            image in entry.get("repoTags", []) or short in entry.get("repoTags", [])
            for entry in images
        )

    def build_go_image(self, source_path: Path, image: str, binary_name: str) -> None:
        if self.image_loaded(image):
            return
        with TemporaryDirectory(prefix=f"rezono-{binary_name}-") as directory:
            build_dir = Path(directory)
            binary = build_dir / binary_name
            env = {
                **os.environ,
                "CGO_ENABLED": "0",
                "GOOS": "linux",
                "GOARCH": "amd64",
                "GOTOOLCHAIN": "local",
                "GO111MODULE": "off",
            }
            run(
                "go",
                "build",
                "-trimpath",
                "-buildvcs=false",
                "-ldflags=-buildid=",
                "-o",
                str(binary),
                str(source_path),
                limit=110,
                env=env,
            )
            (build_dir / "Dockerfile").write_text(
                f"FROM scratch\nCOPY {binary_name} /{binary_name}\nUSER 65534:65534\n",
                encoding="utf-8",
            )
            run("docker", "build", "--network=none", "--tag", image, str(build_dir), limit=80)
            try:
                run("kind", "load", "docker-image", image, "--name", CLUSTER_NAME, limit=90)
            finally:
                run("docker", "image", "rm", "--no-prune", image)

    def ensure_recorder_image(self) -> None:
        self.build_go_image(PROBE_SOURCE, RECORDER_IMAGE, "network-probe")

    def next_observed_at(self) -> str:
        """Return a strictly monotonic RFC3339 UTC timestamp with microsecond precision."""
        now_us = time_ns() // 1000
        if now_us <= self._last_tick_us:
            now_us = self._last_tick_us + 1
        self._last_tick_us = now_us
        seconds, micros = divmod(now_us, 1_000_000)
        stamp = datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
        return f"{stamp}.{micros:06d}Z"

    def make_event(self, feature: str, kind: str, **fields: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "run": self.run,
            "attempt": self.attempt,
            "feature": feature,
            "kind": kind,
            "observed_at": self.next_observed_at(),
            **fields,
        }
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()
        return {**payload, "evidence": f"sha256:{digest}"}

    def record_job(self, feature: str, events: list[dict[str, Any]]) -> str:
        self.ensure_namespace(NAMESPACE)
        self.ensure_recorder_image()
        job_name = f"record-{feature}-{self.run}-{self.attempt}"
        config_name = f"{job_name}-evidence"
        labels = {
            "rezono.org/management-feature": feature,
            "rezono.org/recorder-run": f"{self.run}-{self.attempt}",
        }
        payload = "".join(json.dumps(event, sort_keys=True) + "\n" for event in events)
        self.apply({
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {"name": config_name, "namespace": NAMESPACE, "labels": labels},
            "immutable": True,
            "data": {"observed.jsonl": payload},
        })
        self.apply({
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {"name": job_name, "namespace": NAMESPACE, "labels": labels},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 40,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "restartPolicy": "Never",
                        "automountServiceAccountToken": False,
                        "containers": [{
                            "name": "recorder",
                            "image": RECORDER_IMAGE,
                            "imagePullPolicy": "Never",
                            "command": ["/network-probe", "record", "/evidence/observed.jsonl"],
                            "volumeMounts": [{"name": "observations", "mountPath": "/evidence", "readOnly": True}],
                        }],
                        "volumes": [{"name": "observations", "configMap": {"name": config_name}}],
                    },
                },
            },
        })
        self.wait(f"job/{job_name}", "--for=condition=Complete", "--timeout=45s", namespace=NAMESPACE, limit=55)
        job = self.read("get", "job", job_name, namespace=NAMESPACE)
        uid = job["metadata"]["uid"]
        print(f"Recorded {len(events)} actual observations in {job_name} (uid={uid})", flush=True)
        return uid
