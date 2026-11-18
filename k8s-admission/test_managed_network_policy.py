"""A transport tuple has the same meaning in ingress and egress."""

from copy import deepcopy

import pytest


def selected(service):
    return {"matchLabels": {"rezono.org/service": service}}


def grant(direction):
    incoming = direction == "Ingress"
    return {
        "apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy",
        "metadata": {"name": "sample-grant", "namespace": "blue"},
        "spec": {"podSelector": selected("web" if incoming else "reader"),
                 "policyTypes": [direction], direction.lower(): [{
                     ("from" if incoming else "to"): [
                         {"podSelector": selected("reader" if incoming else "web")}],
                     "ports": [{"protocol": "TCP", "port": 443}]}]}}


@pytest.mark.xfail(strict=True, reason="Implement managed NetworkPolicy preflight in k8s-admission/managed_network_policy.py. Read decisions/k8s-admission-rules.md; use the publication for both directions and the renderer service label.")
def test_managed_policy_baseline_and_directional_grants():
    from managed_network_policy import evaluate_network_policy

    publication = {"namespace": "blue", "digest": "d" * 64,
                   "flows": [{"source": "reader", "destination": "web", "port": 443}]}
    baseline = grant("Ingress")
    baseline["spec"] = {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}
    assert evaluate_network_policy(baseline, publication)["allowed"] is True
    for direction, peer_key in [("Ingress", "from"), ("Egress", "to")]:
        exact = grant(direction)
        assert evaluate_network_policy(exact, publication)["allowed"] is True
        unrestricted = deepcopy(baseline)
        unrestricted["spec"][direction.lower()] = [{}]
        wide_peer = deepcopy(exact)
        rule = wide_peer["spec"][direction.lower()][0]
        rule[peer_key] = [{"podSelector": {}}]
        wide_port = deepcopy(exact)
        wide_port["spec"][direction.lower()][0]["ports"][0]["endPort"] = 444
        wrong_protocol = deepcopy(exact)
        wrong_protocol["spec"][direction.lower()][0]["ports"][0]["protocol"] = "UDP"
        reversed_grant = deepcopy(exact)
        spec = reversed_grant["spec"]
        peer = spec[direction.lower()][0][peer_key][0]
        peer["podSelector"], spec["podSelector"] = spec["podSelector"], peer["podSelector"]
        for wider in [unrestricted, wide_peer, wide_port, wrong_protocol, reversed_grant]:
            result = evaluate_network_policy(wider, publication)
            assert result["allowed"] is False, wider
            assert "in-zone-flow" in result["message"]
            assert publication["digest"] in result["message"]
