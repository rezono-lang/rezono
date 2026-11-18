"""Exercise native validation on the shared disposable API server."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess

import pytest
import yaml


FIXTURES = Path(__file__).parent / "fixtures" / "server"


def fixture(name):
    return yaml.safe_load((FIXTURES / name).read_text(encoding="utf-8"))


def kubectl(config, *args, obj=None):
    return subprocess.run(["kubectl", "--kubeconfig", config, "--request-timeout=20s", *args],
                          input=json.dumps(obj) if obj is not None else None,
                          text=True, capture_output=True, timeout=30)


def fetch(config, *args):
    command = kubectl(config, "get", *args, "-o", "json")
    assert command.returncode == 0, command.stderr
    return json.loads(command.stdout)


@pytest.mark.cluster
@pytest.mark.xfail(strict=True, reason="Depends on the shared disposable cluster, complete policies and desired release reconciliation. Connect the existing cluster setup to the admission test kubeconfig and release, per decisions/k8s-admission-server-evidence.md.")
def test_reconciled_admission_release_on_the_api_server():
    config = os.environ["REZONO_ADMISSION_TEST_KUBECONFIG"]
    assert Path(config).is_file()
    from bindings import render_binding
    from policy_renderer import render_policy

    desired = fixture("publication.yaml")
    digest = desired["spec"]["digest"]
    name = desired["metadata"]["name"]
    app = fetch(config, "applications.argoproj.io", os.environ["REZONO_ADMISSION_TEST_APPLICATION"],
                "-n", os.environ["REZONO_ADMISSION_TEST_APPLICATION_NAMESPACE"])
    revision = subprocess.check_output(["git", "-C", str(FIXTURES), "rev-parse", "HEAD"], text=True).strip()
    assert app["status"]["sync"]["revision"] == revision
    assert app["status"]["sync"]["status"] == "Synced"
    tracked = {(row["kind"], row.get("namespace", ""), row["name"])
               for row in app["status"]["resources"] if row.get("status") == "Synced"}
    assert ("NamespacePublication", "admission-blue", name) in tracked
    for ns in ["admission-blue", "admission-green"]:
        assert fetch(config, "namespace", ns)["metadata"]["labels"]["rezono.dev/admission"] == "enabled"
    assert fetch(config, "namespacepublications.admission.rezono.org", name,
                 "-n", "admission-blue")["spec"] == desired["spec"]
    green = fetch(config, "namespacepublications.admission.rezono.org", "-n", "admission-green")
    assert all(obj["metadata"]["name"] != name for obj in green["items"])

    for rule, filename in [("verified-supply", "pod.yaml"), ("in-zone-flow", "flow.yaml")]:
        binding = render_binding(rule=rule, digest=digest, parameter_name=name)
        policy = render_policy(rule=rule, digest=digest)
        assert ("ValidatingAdmissionPolicy", "", policy["metadata"]["name"]) in tracked
        assert ("ValidatingAdmissionPolicyBinding", "", binding["metadata"]["name"]) in tracked
        bound = fetch(config, "validatingadmissionpolicybinding", binding["metadata"]["name"])
        live = fetch(config, "validatingadmissionpolicy", policy["metadata"]["name"])
        assert bound["spec"]["policyName"] == live["metadata"]["name"]
        assert bound["spec"]["paramRef"] == binding["spec"]["paramRef"]
        assert live["spec"]["paramKind"] == policy["spec"]["paramKind"]
        assert live["spec"]["validations"] == policy["spec"]["validations"]
        assert live["status"]["observedGeneration"] == live["metadata"]["generation"]
        assert live["status"]["typeChecking"].get("expressionWarnings", []) == []

        good = fixture(filename)
        allowed = kubectl(config, "create", "--dry-run=server", "-f", "-", "-o", "json", obj=good)
        assert allowed.returncode == 0, allowed.stderr
        returned = json.loads(allowed.stdout)
        assert returned["kind"] == good["kind"] and returned["metadata"]["namespace"] == "admission-blue"

        unknown = deepcopy(good)
        unknown["metadata"]["namespace"] = "admission-green"
        disallowed = deepcopy(good)
        if rule == "verified-supply":
            disallowed["spec"]["containers"][0]["image"] = "registry.example.org/sample/app@sha256:" + "b" * 64
        else:
            disallowed["spec"]["ingress"][0]["ports"][0]["port"] = 8443
        for rejected in [disallowed, unknown]:
            denied = kubectl(config, "create", "--dry-run=server", "-f", "-", obj=rejected)
            assert denied.returncode != 0
            assert (live["metadata"]["name"] in denied.stderr or
                    bound["metadata"]["name"] in denied.stderr), denied.stderr
            assert rule in denied.stderr and digest in denied.stderr.replace(".", "").replace("-", "")
