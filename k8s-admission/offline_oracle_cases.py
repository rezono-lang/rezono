"""Both offline tools replay the same Kubernetes request and release documents."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess

import yaml
from checked_release_fixture import MANIFEST_KEY, publish_evidence


ROOT = Path(__file__).parent


def check_offline_oracle(driver, tmp_path):
    from admission_release import render_release

    def load(name):
        return yaml.safe_load((ROOT / "fixtures" / "server" / name).read_text(encoding="utf-8"))

    publication = load("publication.yaml")
    store = publish_evidence(tmp_path / "checked")
    release = render_release(["admission-blue", "admission-green"], [publication],
                             store=store, manifest_key=MANIFEST_KEY)
    file = tmp_path / "release.json"
    file.write_text(json.dumps({"apiVersion": "v1", "kind": "List", "items": release}), encoding="utf-8")
    for filename, group, resource in [("pod.yaml", "", "pods"), ("flow.yaml", "networking.k8s.io", "networkpolicies")]:
        allowed = load(filename)
        denied = deepcopy(allowed)
        if resource == "pods":
            denied["spec"]["containers"][0]["image"] = "registry.example.org/sample/app@sha256:" + "b" * 64
        else:
            denied["spec"]["ingress"][0]["ports"][0]["port"] = 8443
        for obj, expected in [(allowed, True), (denied, False)]:
            review = {"apiVersion": "admission.k8s.io/v1", "kind": "AdmissionReview",
                      "request": {"uid": "e01a61c9-2ca7-4007-9287-de95c60c1046", "operation": "CREATE",
                                  "kind": {"group": group, "version": "v1", "kind": obj["kind"]},
                                  "resource": {"group": group, "version": "v1", "resource": resource},
                                  "namespace": obj["metadata"]["namespace"], "name": obj["metadata"]["name"],
                                  "userInfo": {"username": "fixture-reader"}, "object": obj, "dryRun": True}}
            proc = subprocess.run(["go", "run", ".", "--release", str(file)], cwd=ROOT / "oracles" / driver,
                                  input=json.dumps(review), text=True, capture_output=True, timeout=180)
            assert proc.returncode == 0, proc.stderr
            response = json.loads(proc.stdout)["response"]
            assert response["uid"] == review["request"]["uid"]
            assert response["allowed"] is expected
            if not expected:
                rule = "verified-supply" if resource == "pods" else "in-zone-flow"
                assert rule in response["status"]["message"]
                assert publication["spec"]["digest"] in response["status"]["message"]
