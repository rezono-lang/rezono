"""The shared cluster disables the default CNI before installing Cilium."""

import pytest
import yaml

from cluster_scenarios import CLUSTER


@pytest.mark.xfail(strict=True, reason="Read decisions/shared-disposable-cluster.md. Implement loop/cluster/kind.yaml for the single runner-local synthetic fixture. Pin its node image by digest.")
def test_kind_fixture_config():
    config = yaml.safe_load((CLUSTER / "kind.yaml").read_text(encoding="utf-8"))
    assert (config["apiVersion"], config["kind"]) == ("kind.x-k8s.io/v1alpha4", "Cluster")
    assert config["networking"]["disableDefaultCNI"] is True
    nodes = config["nodes"]
    assert sum(node["role"] == "control-plane" for node in nodes) == 1
    for node in nodes:
        image, digest = node["image"].rsplit("@sha256:", 1)
        assert image.startswith("kindest/node:") and len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)
