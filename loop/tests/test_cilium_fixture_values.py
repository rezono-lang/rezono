"""Cilium policy enforcement and Hubble share one pinned chart installation."""

import pytest
import yaml

from cluster_scenarios import CLUSTER


@pytest.mark.xfail(strict=True, reason="Read decisions/shared-disposable-cluster.md. Implement loop/cluster/cilium-values.yaml enabling policy enforcement and Hubble relay on the synthetic fixture.")
def test_cilium_fixture_values():
    values = yaml.safe_load((CLUSTER / "cilium-values.yaml").read_text(encoding="utf-8"))
    assert values["policyEnforcementMode"] in {"default", "always"}
    assert values["hubble"]["enabled"] is True
    assert values["hubble"]["relay"]["enabled"] is True
    assert values["hubble"].get("ui", {}).get("enabled", False) is False
