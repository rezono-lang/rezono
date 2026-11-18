"""Hand-calculated ingress cases from decisions/k8s-admission-rules.md."""

import pytest


def service(name):
    return {"matchLabels": {"app.kubernetes.io/name": name}}


@pytest.mark.xfail(strict=True, reason="Implement flow preflight in k8s-admission/flow.py using the projected namespace publication; read decisions/k8s-admission-rules.md.")
def test_ingress_matches_complete_flow_tuples():
    from flow import evaluate_ingress

    digest = "d" * 64
    publication = {"namespace": "sample", "digest": digest, "flows": [
        {"source": "reader", "destination": "web", "port": 443},
        {"source": "probe", "destination": "web", "port": 8443},
    ]}
    for peers, ports, allowed in [
        ([], [], True),
        (["reader"], [443], True),
        (["probe"], [8443], True),
        (["reader"], [8443], False),
        (["reader", "probe"], [443, 8443], False),
    ]:
        ingress = [{"from": [{"podSelector": service(p)} for p in peers],
                    "ports": [{"protocol": "TCP", "port": p} for p in ports]}] if peers else []
        policy = {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
                  "metadata": {"name": "demo", "namespace": "sample"},
                  "spec": {"policyTypes": ["Ingress"], "podSelector": service("web"),
                           "ingress": ingress}}
        result = evaluate_ingress(policy, publication)
        assert result["allowed"] is allowed, (peers, ports)
        if not allowed:
            assert "in-zone-flow" in result["message"]
            assert digest in result["message"]
