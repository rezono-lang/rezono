"""Preflight reads one incoming object as request rows through its binding.

See decisions/k8s-admission-translator.md, "The binding". The rows and missing places are calculated by hand.
The flow binding also reads back exactly the grants the platform renderer wrote.
"""

from pathlib import Path

import pytest
from translator_support import IMAGE_A, IMAGE_B, fixture, load_program

ROOT = Path(__file__).parent.resolve()
LABELS = {"app.kubernetes.io/name": "web"}
APP = {"name": "app", "image": IMAGE_A}
SERVICE = 'object.metadata.labels["app.kubernetes.io/name"]'
LOCAL = 'object.spec.podSelector.matchLabels["rezono.org/service"]'


def review(obj, namespace="blue"):
    return {"namespace": namespace, "operation": "CREATE", "object": obj}


def pod(labels=None, **spec):
    metadata = {"name": "probe"} if labels is None else {"name": "probe", "labels": labels}
    return {"apiVersion": "v1", "kind": "Pod", "metadata": metadata, "spec": spec}


def peer(service):
    return {"podSelector": {"matchLabels": {"rezono.org/service": service}}}


def policy(selector=None, **spec):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "probe"},
            "spec": {"podSelector": {"matchLabels": {"rezono.org/service": "web"}} if selector is None else selector,
                     **spec}}


POD_CASES = [
    (pod(LABELS, containers=[APP], initContainers=[{"name": "init", "image": IMAGE_B}]),
     [("blue", "web", IMAGE_A), ("blue", "web", IMAGE_B)], []),
    (pod(LABELS, containers=[APP, {"name": "side", "image": IMAGE_A}]), [("blue", "web", IMAGE_A)], []),
    (pod(LABELS, containers=[]), [], []),
    (pod({}, containers=[APP]), [], [SERVICE]),
    (pod(None, containers=[APP, APP]), [], [SERVICE]),
    (pod(LABELS), [], ["object.spec.containers"]),
    (pod(LABELS, containers=APP), [], ["object.spec.containers"]),
    (pod(LABELS, containers=["app"]), [], ["object.spec.containers[0]"]),
    (pod(LABELS, containers=[APP, {"name": "side"}]), [], ["object.spec.containers[1].image"]),
    (pod(LABELS, containers=[{"name": "app", "image": 7}]), [], ["object.spec.containers[0].image"]),
    (pod({}, containers=[APP], initContainers=[{"name": "init"}]), [],
     [SERVICE, "object.spec.initContainers[0].image"]),
]
INGRESS = {"from": [peer("reader"), peer("probe")],
           "ports": [{"port": 443}, {"protocol": "UDP", "port": 53, "endPort": 54}]}
POLICY_CASES = [
    (policy(policyTypes=["Ingress"], ingress=[INGRESS]),
     [("blue", "probe", "web", "TCP", 443), ("blue", "probe", "web", "UDP", 53), ("blue", "probe", "web", "UDP", 54),
      ("blue", "reader", "web", "TCP", 443), ("blue", "reader", "web", "UDP", 53), ("blue", "reader", "web", "UDP", 54)],
     []),
    (policy(egress=[{"to": [peer("dns")], "ports": [{"protocol": "UDP", "port": 53}]}]),
     [("blue", "web", "dns", "UDP", 53)], []),
    (policy({}, policyTypes=["Ingress", "Egress"]), [], []),
    (policy(ingress=[{"from": [{"ipBlock": {"cidr": "192.0.2.0/24"}}], "ports": [{"port": 443}]}]), [],
     ["object.spec.ingress[0].from[0]"]),
    (policy(ingress=[{"from": [{**peer("reader"), "namespaceSelector": {}}], "ports": [{"port": 443}]}]), [],
     ["object.spec.ingress[0].from[0]"]),
    (policy(ingress=[{"from": [], "ports": [{"port": 443}]}]), [], ["object.spec.ingress[0].from"]),
    (policy(ingress=[{"ports": [{"port": 443}]}]), [], ["object.spec.ingress[0].from"]),
    (policy(ingress=[{"from": [peer("reader")]}]), [], ["object.spec.ingress[0].ports"]),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 443}], "extra": True}]), [],
     ["object.spec.ingress[0]"]),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": "https"}]}]), [],
     ["object.spec.ingress[0].ports[0].port"]),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 444, "endPort": 443}]}]), [],
     ["object.spec.ingress[0].ports[0].port"]),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 443, "protocol": 6}]}]), [],
     ["object.spec.ingress[0].ports[0].protocol"]),
    (policy(egress=[{"to": [peer("dns"), {"podSelector": {}}], "ports": [{"port": 53}]}]), [],
     ['object.spec.egress[0].to[1].podSelector.matchLabels["rezono.org/service"]']),
    (policy({}, ingress=[{"from": [peer("reader")], "ports": [{"port": 443}]}]), [], [LOCAL]),
]


def test_request_rows(monkeypatch):
    from request_rows import read_request_rows

    for rule, relation, cases in [("verified-supply", "pod_image", POD_CASES),
                                  ("in-zone-flow", "requested_flow", POLICY_CASES)]:
        binding, prog = fixture(f"{rule}.binding.yaml"), load_program(f"{rule}.rules.yaml")
        for obj, rows, missing in cases:
            assert read_request_rows(binding, prog, review(obj)) == {"rows": {relation: rows}, "missing": missing}, obj

    monkeypatch.syspath_prepend(str(ROOT.parent / "examples" / "platform"))
    from network_policy import render_network_policies

    binding, prog = fixture("in-zone-flow.binding.yaml"), load_program("in-zone-flow.rules.yaml")
    grants = [
        {"source": "idp", "destination": "dns", "protocol": "UDP", "fromPort": 53, "toPort": 54},
        {"source": "reader", "destination": "web", "protocol": "TCP", "fromPort": 443, "toPort": 443},
    ]
    read = [read_request_rows(binding, prog, review(obj)) for obj in render_network_policies("blue", grants)]
    assert all(result["missing"] == [] for result in read)
    assert sorted(len(result["rows"]["requested_flow"]) for result in read) == [0, 1, 1, 2, 2]
    assert {row for result in read for row in result["rows"]["requested_flow"]} == {
        ("blue", "idp", "dns", "UDP", 53), ("blue", "idp", "dns", "UDP", 54), ("blue", "reader", "web", "TCP", 443),
    }
