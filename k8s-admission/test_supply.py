"""Hand-calculated Pod cases from decisions/k8s-admission-rules.md."""

import pytest


def image(letter):
    return "registry.example.org/sample/app@sha256:" + letter * 64


@pytest.mark.xfail(strict=True, reason="Implement supply preflight in k8s-admission/supply.py using the projected namespace publication; read decisions/k8s-admission-rules.md.")
def test_pod_images_match_service_and_namespace():
    from supply import evaluate_pod

    digest = "d" * 64
    publication = {"namespace": "sample", "digest": digest,
                   "images": [{"service": "web", "image": image(c)} for c in "ab"]}
    for namespace, primary, init, allowed in [
        ("sample", "a", None, True),
        ("sample", "a", "b", True),
        ("sample", "c", None, False),
        ("sample", "a", "c", False),
        ("another", "a", None, False),
    ]:
        pod = {"apiVersion": "v1", "kind": "Pod",
               "metadata": {"name": "demo", "namespace": namespace,
                            "labels": {"app.kubernetes.io/name": "web"}},
               "spec": {"containers": [{"name": "app", "image": image(primary)}]}}
        if init:
            pod["spec"]["initContainers"] = [{"name": "setup", "image": image(init)}]
        result = evaluate_pod(pod, publication)
        assert result["allowed"] is allowed, (namespace, primary, init)
        if not allowed and namespace == "sample":
            assert "verified-supply" in result["message"]
            assert digest in result["message"]
