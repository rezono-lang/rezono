"""CEL reads one incoming object as request rows, as its binding says.

See decisions/k8s-admission-translator.md, "The binding" and "Request sources". The expected rows and
missing-input verdicts are calculated by hand from the bindings in fixtures/translator/.
"""

import json

import pytest
from translator_support import IMAGE_A, IMAGE_B, IMAGE_C, fixture, load_program, run_cel

ROOTS = {"object": "object.obj", "request": "object.req"}
WEB = {"matchLabels": {"rezono.org/service": "web"}}


def peer(service):
    return {"podSelector": {"matchLabels": {"rezono.org/service": service}}}


def pod(labels, **spec):
    return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "probe", "labels": labels}, "spec": spec}


def policy(**spec):
    return {"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "probe"},
            "spec": {"podSelector": WEB, **spec}}


def image_rows(*images):
    return [{"namespace": "blue", "service": "web", "image": image} for image in images]


def flow(source, destination, protocol, start, end=None):
    return {"namespace": "blue", "source": source, "destination": destination, "protocol": protocol,
            "port": {"start": start, "end": start if end is None else end}}


APP = {"name": "app", "image": IMAGE_A}
LABELS = {"app.kubernetes.io/name": "web"}
PODS = [
    (pod(LABELS, containers=[APP], initContainers=[{"name": "init", "image": IMAGE_B}]), image_rows(IMAGE_A, IMAGE_B)),
    (pod(LABELS, containers=[APP], ephemeralContainers=[{"name": "debug", "image": IMAGE_C}]),
     image_rows(IMAGE_A, IMAGE_C)),
    (pod(LABELS, containers=[APP, {"name": "side", "image": IMAGE_A}]), image_rows(IMAGE_A, IMAGE_A)),
    (pod(LABELS, containers=[]), []),
    (pod({}, containers=[APP]), None),
    (pod({"app": "web"}, containers=[APP]), None),
    (pod(LABELS), None),
    (pod(LABELS, containers=[{"name": "app"}]), None),
    (pod(LABELS, containers=[{"name": "app", "image": 7}]), None),
    (pod(LABELS, containers=[APP], initContainers=[{"name": "init"}]), None),
]
INGRESS = {"from": [peer("reader"), peer("probe")], "ports": [{"port": 443}, {"protocol": "UDP", "port": 53, "endPort": 54}]}
POLICIES = [
    (policy(policyTypes=["Ingress"], ingress=[INGRESS]),
     [flow("reader", "web", "TCP", 443), flow("reader", "web", "UDP", 53, 54),
      flow("probe", "web", "TCP", 443), flow("probe", "web", "UDP", 53, 54)]),
    (policy(policyTypes=["Egress"], egress=[{"to": [peer("dns")], "ports": [{"protocol": "UDP", "port": 53}]}]),
     [flow("web", "dns", "UDP", 53)]),
    ({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "baseline"},
      "spec": {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}}, []),
    (policy(policyTypes=["Ingress"], ingress=[]), []),
    (policy(ingress=[{"from": [{"ipBlock": {"cidr": "192.0.2.0/24"}}], "ports": [{"port": 443}]}]), None),
    (policy(ingress=[{"from": [{**peer("reader"), "namespaceSelector": {}}], "ports": [{"port": 443}]}]), None),
    (policy(ingress=[{"from": [], "ports": [{"port": 443}]}]), None),
    (policy(ingress=[{"from": [peer("reader")]}]), None),
    (policy(ingress=[{"ports": [{"port": 443}]}]), None),
    (policy(ingress=[{"from": [peer("reader")], "ports": []}]), None),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": "https"}]}]), None),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 444, "endPort": 443}]}]), None),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 0}]}]), None),
    (policy(ingress=[{"from": [peer("reader")], "ports": [{"port": 65535, "endPort": 65536}]}]), None),
    (policy(egress=[{"to": [{"podSelector": {"matchLabels": {"app": "dns"}}}], "ports": [{"port": 53}]}]), None),
    ({"apiVersion": "networking.k8s.io/v1", "kind": "NetworkPolicy", "metadata": {"name": "wide"},
      "spec": {"podSelector": {}, "ingress": [{"from": [peer("reader")], "ports": [{"port": 443}]}]}}, None),
]


def match(var, columns):
    parts = []
    for name, value in columns.items():
        if isinstance(value, dict):
            parts += [f"{var}.{name}.start == {value['start']}", f"{var}.{name}.end == {value['end']}"]
        else:
            parts.append(f"{var}.{name} == {value}")
    return " && ".join(parts)


def test_cel_request_sources():
    from cel_request import missing, quantify

    samples, expected = [], []
    for rule, relation, keys, cases in [
        ("verified-supply", "pod_image", ["image", "namespace", "service"], PODS),
        ("in-zone-flow", "requested_flow", ["destination", "namespace", "port", "protocol", "source"], POLICIES),
    ]:
        binding, prog = fixture(f"{rule}.binding.yaml"), load_program(f"{rule}.rules.yaml")
        calls = []

        def body(relation_name, columns, rows=None, calls=calls):
            calls.append((relation_name, sorted(columns)))
            if rows is None:
                return "false"
            return f"{json.dumps(rows)}.exists(x, {match('x', columns)})"

        absent = missing(binding, prog, ROOTS)
        assert isinstance(absent, str)
        empty = quantify(binding, prog, ROOTS, body)
        assert isinstance(empty, str)
        assert calls and all(call == (relation, keys) for call in calls)
        for obj, rows in cases:
            sample = {"obj": obj, "req": {"namespace": "blue"}}
            samples.append((sample, {}, absent))
            expected.append(rows is None)
            if rows is None:
                continue
            samples.append((sample, {}, empty))
            expected.append(not rows)
            exact = quantify(binding, prog, ROOTS, lambda name, columns, rows=rows: body(name, columns, rows))
            samples.append((sample, {}, exact))
            expected.append(True)
            for row in rows:
                others = [other for other in rows if other != row]
                without = quantify(binding, prog, ROOTS, lambda name, columns, rows=others: body(name, columns, rows))
                samples.append((sample, {}, without))
                expected.append(False)
    results = run_cel(samples)
    if results is not None:
        assert results == expected
