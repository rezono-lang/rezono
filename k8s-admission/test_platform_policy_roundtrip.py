"""Apply admission to the actual platform generator's manifest bundle."""

from pathlib import Path

import pytest
import yaml


@pytest.mark.xfail(strict=True, reason="Depends on the platform NetworkPolicy generator and test_managed_policy_baseline_and_directional_grants. Implement the release-bound batch preflight in k8s-admission/rendered_preflight.py. Read decisions/k8s-admission-rules.md.")
def test_real_platform_policy_bundle_passes_preflight(monkeypatch):
    platform_dir = Path(__file__).resolve().parents[1] / "examples" / "platform"
    monkeypatch.syspath_prepend(str(platform_dir))
    from network_policy import render_network_policies
    from rendered_preflight import assess_rendered_policies

    namespace = yaml.safe_load((Path(__file__).parent / "fixtures" / "managed-blue.yaml")
                               .read_text(encoding="utf-8"))
    assert namespace["metadata"]["labels"]["rezono.dev/admission"] == "enabled"
    manifests = list(render_network_policies(namespace["metadata"]["name"], [
        {"source": "reader", "destination": "web",
         "protocol": "TCP", "fromPort": 443, "toPort": 443}]))
    assert all(m["kind"] == "NetworkPolicy" and m["metadata"]["namespace"] == "blue"
               for m in manifests)
    baseline = [m for m in manifests if m["spec"]["podSelector"] == {}]
    assert len(baseline) == 1
    assert set(baseline[0]["spec"]["policyTypes"]) == {"Ingress", "Egress"}
    assert not baseline[0]["spec"].get("ingress") and not baseline[0]["spec"].get("egress")
    for direction in ("ingress", "egress"):
        assert any(m["spec"].get(direction) for m in manifests)
    names = [m["metadata"]["name"] for m in manifests]
    assert len(set(names)) == len(names)
    publication = {"namespace": "blue", "digest": "d" * 64,
                   "flows": [{"source": "reader", "destination": "web", "port": 443}]}
    results = assess_rendered_policies(manifests, publication)
    assert results == {name: {"allowed": True, "digest": publication["digest"]} for name in names}
    withdrawn = dict(publication, flows=[], digest="e" * 64)
    changed = assess_rendered_policies(manifests, withdrawn)
    assert set(changed) == set(names)
    for manifest in manifests:
        answer = changed[manifest["metadata"]["name"]]
        assert answer["allowed"] is (manifest in baseline)
        assert answer["digest"] == withdrawn["digest"]
