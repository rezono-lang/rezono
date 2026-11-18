"""Read only the fixed Cilium and Hubble objects of the designated kind fixture."""

import json
import os
from pathlib import Path
import subprocess

import pytest


@pytest.mark.cluster
def test_cluster_live_identity():
    config = Path(os.environ["REZONO_CLUSTER_KUBECONFIG"]).resolve(strict=True)
    assert config.is_relative_to(Path(os.environ["RUNNER_TEMP"]).resolve(strict=True))
    kubectl = ["kubectl", "--kubeconfig", str(config), "--request-timeout=15s"]
    context = subprocess.check_output([*kubectl, "config", "current-context"], text=True, timeout=20).strip()
    assert context == "kind-rezono-fixture"
    for resource, name, field in [("daemonset", "cilium", "numberReady"), ("deployment", "hubble-relay", "readyReplicas")]:
        raw = subprocess.check_output([*kubectl, "--context", context, "-n", "kube-system", "get",
                                       resource, name, "-o", "json"], text=True, timeout=20)
        document = json.loads(raw)
        assert document["metadata"]["namespace"] == "kube-system" and document["metadata"]["name"] == name
        assert document["status"][field] >= 1
