"""Install and serve the admission release for the runner-owned kind fixture."""

import argparse
from hashlib import sha256
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

import yaml


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
ADMISSION = ROOT / "k8s-admission"
ARGO_IMAGE = (
    "quay.io/argoproj/argocd@sha256:967306562700bc6f4bab7c247caf69892d77624b019ca510e86b4b00fc9c5584"
)
REDIS_IMAGE = (
    "public.ecr.aws/docker/library/redis@sha256:de4d18872bf67ad0bd62224a712263975ca1d53b9b1d0d5d076082e7fa887890"
)
MIRRORED_PATH = "/rezono.git"
PLUGIN = "rezono-admission-fixture"
ADMISSION_WAVES = {
    "CustomResourceDefinition": "-2",
    "Namespace": "-2",
    "NamespacePublication": "-1",
    "ValidatingAdmissionPolicy": "0",
    "ValidatingAdmissionPolicyBinding": "1",
}


def render_release() -> bytes:
    from admission_release import render_release as compose
    from checked_release_fixture import MANIFEST_KEY, publish_evidence

    publication = yaml.safe_load((ADMISSION / "fixtures/server/publication.yaml").read_bytes())
    with TemporaryDirectory(prefix="rezono-admission-") as directory:
        store = publish_evidence(Path(directory))
        objects = compose(["admission-blue", "admission-green"], [publication], store=store,
                          manifest_key=MANIFEST_KEY)
    # The API server type-checks a policy when it first observes that generation.
    # Publish the parameter API and an actual record before the policies exist.
    for obj in objects:
        annotations = obj["metadata"].setdefault("annotations", {})
        annotations["argocd.argoproj.io/sync-wave"] = ADMISSION_WAVES[obj["kind"]]
    return yaml.safe_dump_all(objects, sort_keys=False).encode("utf-8")


def render_argo(source: Path) -> None:
    objects = [row for row in yaml.safe_load_all(source.read_bytes()) if row]
    for obj in objects:
        if obj["kind"] not in {"Deployment", "StatefulSet"}:
            continue
        spec = obj["spec"]["template"]["spec"]
        for container in [*spec.get("initContainers", ()), *spec["containers"]]:
            container["image"] = {
                "quay.io/argoproj/argocd:v3.6.1": ARGO_IMAGE,
                "public.ecr.aws/docker/library/redis:8.10.1-alpine": REDIS_IMAGE,
            }[container["image"]]

    repository, = [obj for obj in objects if obj["kind"] == "Deployment"
                   and obj["metadata"]["name"] == "argocd-repo-server"]
    spec = repository["spec"]["template"]["spec"]
    copyutil, = [row for row in spec["initContainers"] if row["name"] == "copyutil"]
    repo_server, = [row for row in spec["containers"] if row["name"] == "argocd-repo-server"]
    runtime, = [mount for mount in copyutil["volumeMounts"] if mount["name"] == "var-files"]
    plugins, = [mount for mount in repo_server["volumeMounts"] if mount["name"] == "plugins"]
    config_dir = PurePosixPath(plugins["mountPath"]).with_name("config")
    spec["volumes"].extend([
        {"name": "admission-plugin", "configMap": {"name": PLUGIN}},
        {"name": "admission-plugin-tmp", "emptyDir": {}},
    ])
    spec["containers"].append({
        "name": PLUGIN,
        "image": ARGO_IMAGE,
        "command": [str(PurePosixPath(runtime["mountPath"]) / "argocd-cmp-server")],
        "securityContext": {
            "runAsNonRoot": True,
            "runAsUser": 999,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
        },
        "volumeMounts": [
            runtime,
            plugins,
            {"name": "admission-plugin", "mountPath": str(config_dir), "readOnly": True},
            {"name": "admission-plugin-tmp", "mountPath": "/tmp"},
        ],
    })
    objects.insert(0, {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {"name": PLUGIN},
        "data": {"plugin.yaml": (HERE / "admission-cmp.yaml").read_text(encoding="utf-8")},
    })
    print(yaml.safe_dump_all(objects, sort_keys=False), end="")


def serve(address: str, port: int, mirror: Path, revision: str) -> None:
    if subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip() != revision:
        raise ValueError("renderer checkout differs from the mirrored revision")
    renderer = sha256((ADMISSION / "admission_release.py").read_bytes()).hexdigest()
    publication = sha256((ADMISSION / "fixtures/server/publication.yaml").read_bytes()).hexdigest()
    release_path = f"/release/{revision}/{renderer}/{publication}"
    sys.path.insert(0, str(ADMISSION))

    class Request(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            request = urlsplit(self.path)
            if request.path == "/healthz" and not request.query:
                self.respond(200, b"ready\n", {"Content-Type": "text/plain"})
            elif request.path == release_path and not request.query:
                self.release()
            elif request.path == f"{MIRRORED_PATH}/info/refs" and request.query == "service=git-upload-pack":
                self.git(request.path, request.query, b"")
            else:
                self.send_error(404)

        def do_POST(self) -> None:
            if self.path != f"{MIRRORED_PATH}/git-upload-pack":
                self.send_error(404)
                return
            size = self.headers.get("Content-Length", "")
            if not size.isascii() or not size.isdigit() or not 0 < int(size) <= 1_048_576:
                self.send_error(400)
                return
            self.git(self.path, "", self.rfile.read(int(size)))

        def respond(self, status: int, body: bytes, headers: dict[str, str]) -> None:
            self.send_response(status)
            for key, value in headers.items():
                if key.lower() != "content-length":
                    self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def release(self) -> None:
            try:
                body = render_release()
            except Exception as exc:
                self.log_error("Admission release rendering failed: %s", exc)
                self.send_error(500)
                return
            self.respond(200, body, {"Content-Type": "application/yaml"})

        def git(self, path: str, query: str, body: bytes) -> None:
            env = {
                **os.environ,
                "GIT_PROJECT_ROOT": str(mirror),
                "GIT_HTTP_EXPORT_ALL": "1",
                "GIT_PROTOCOL": self.headers.get("Git-Protocol", ""),
                "PATH_INFO": path,
                "QUERY_STRING": query,
                "REQUEST_METHOD": self.command,
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(len(body)),
            }
            result = subprocess.run(["git", "http-backend"], input=body, capture_output=True,
                                    env=env, timeout=60, check=True)
            header, _, payload = result.stdout.partition(b"\r\n\r\n")
            fields = dict(line.split(": ", 1) for line in header.decode("ascii").splitlines())
            status = int(fields.pop("Status", "200").split()[0])
            self.respond(status, payload, fields)

    with ThreadingHTTPServer((address, port), Request) as server:
        server.serve_forever()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    install = sub.add_parser("argo")
    install.add_argument("manifest", type=Path)
    bridge = sub.add_parser("serve")
    bridge.add_argument("address")
    bridge.add_argument("port", type=int)
    bridge.add_argument("mirror", type=Path)
    bridge.add_argument("revision")
    args = parser.parse_args()
    if args.operation == "argo":
        render_argo(args.manifest)
    else:
        serve(args.address, args.port, args.mirror, args.revision)


if __name__ == "__main__":
    main()
