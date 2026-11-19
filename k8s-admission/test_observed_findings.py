"""A rule that cannot be a gate still reports what runs without permission.

See decisions/k8s-admission-translator.md, "What CEL cannot do". The findings are calculated by hand.
"""

import pytest
from translator_support import DIGEST, IMAGE_A, IMAGE_B, IMAGE_C, load_program, program

SERVICE = 'object.metadata.labels["app.kubernetes.io/name"]'


def pod(name, namespace, rows=(), missing=()):
    return {"object": {"kind": "Pod", "namespace": namespace, "name": name},
            "rows": {"pod_image": list(rows)}, "missing": list(missing)}


def finding(obj, reason, **detail):
    return {"rule": "verified-supply", "digest": DIGEST, "object": obj, "reason": reason, **detail}


def test_observed_findings():
    from observed_findings import observed_findings

    supply = load_program("verified-supply.rules.yaml")
    signed = [("blue", "web", IMAGE_A), ("blue", "web", IMAGE_B)]
    model = {"image_build": [*signed, ("blue", "web", IMAGE_C)], "image_signature": signed}
    observations = [
        pod("c", "green", [("green", "web", IMAGE_A)]),
        pod("a", "blue", signed),
        pod("d", "blue", missing=[SERVICE]),
        pod("b", "blue", [("blue", "web", IMAGE_A), ("blue", "web", IMAGE_C)]),
    ]
    assert observed_findings(supply, "allow_image", model, observations, rule="verified-supply", digest=DIGEST) == [
        finding({"kind": "Pod", "namespace": "blue", "name": "b"}, "not_admitted",
                relation="pod_image", row=["blue", "web", IMAGE_C]),
        finding({"kind": "Pod", "namespace": "blue", "name": "d"}, "missing_input", places=[SERVICE]),
        finding({"kind": "Pod", "namespace": "green", "name": "c"}, "not_admitted",
                relation="pod_image", row=["green", "web", IMAGE_A]),
    ]
    assert observed_findings(supply, "allow_image", model, observations[1:2], rule="verified-supply",
                             digest=DIGEST) == []

    # A rule over two objects is evaluated on the observed state as a whole.
    key = [("namespace", "string"), ("port", "integer")]
    joined = program(
        {"pod_port": ("base", key), "config_port": ("base", key), "allow": ("derived", key)},
        [("allow", ("allow", ["?n", "?p"]),
          [("pod_port", ["?n", "?p"], "positive"), ("config_port", ["?n", "?p"], "positive")], [])],
    )
    observed = [
        {"object": {"kind": "Pod", "namespace": "blue", "name": "p1"}, "rows": {"pod_port": [("blue", 443)]},
         "missing": []},
        {"object": {"kind": "ConfigMap", "namespace": "blue", "name": "c1"}, "rows": {"config_port": [("blue", 443)]},
         "missing": []},
        {"object": {"kind": "Pod", "namespace": "blue", "name": "p2"}, "rows": {"pod_port": [("blue", 8443)]},
         "missing": []},
    ]
    assert observed_findings(joined, "allow", {}, observed, rule="paired-port", digest=DIGEST) == [{
        "rule": "paired-port", "digest": DIGEST, "object": {"kind": "Pod", "namespace": "blue", "name": "p2"},
        "reason": "not_admitted", "relation": "pod_port", "row": ["blue", 8443],
    }]
