"""Render release-specific Kubernetes admission for verified Pod images."""

import re


_LABEL = "'app.kubernetes.io/name'"
_IMAGE = r"r'^[^@\s]+@sha256:[0-9a-f]{64}$'"


def _check_images(group: str) -> str:
    return (
        f"{group}.all(c, has(c.image) && c.image.matches({_IMAGE}) && "
        "params.spec.images.exists(entry, "
        "entry.service == variables.service && entry.image == c.image))"
    )


def render_supply_policy(*, digest: str) -> dict:
    """Match Pods and verify all requested images against the named publication."""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected a lowercase SHA-256 publication digest")

    labels = "object.metadata.labels"
    service = f"has({labels}) && {_LABEL} in {labels} ? {labels}[{_LABEL}] : ''"
    regular = "object.spec.containers"
    image_checks = [f"size({regular}) > 0 && {_check_images(regular)}"]
    for name in ("initContainers", "ephemeralContainers"):
        group = f"object.spec.{name}"
        image_checks.append(f"(!has({group}) || {_check_images(group)})")
    validations = [
        (f"params.spec.digest == '{digest}'", "publication digest does not match the policy release"),
        ("variables.service != ''", "missing app.kubernetes.io/name service label"),
        (
            "variables.service == '' || (" + " && ".join(image_checks) + ")",
            "image exceeds published verified supply",
        ),
    ]
    rule = "verified-supply"
    return {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "ValidatingAdmissionPolicy",
        "metadata": {"name": f"{rule}.{digest[:32]}.{digest[32:]}"},
        "spec": {
            "failurePolicy": "Fail",
            "paramKind": {"apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication"},
            "matchConstraints": {
                "resourceRules": [
                    {
                        "apiGroups": [""],
                        "apiVersions": ["v1"],
                        "operations": operations,
                        "resources": [resource],
                        "scope": "Namespaced",
                    }
                    for resource, operations in (
                        ("pods", ["CREATE", "UPDATE"]),
                        ("pods/ephemeralcontainers", ["UPDATE"]),
                    )
                ],
            },
            "variables": [{"name": "service", "expression": service}],
            "validations": [
                {"expression": expression, "message": f"{rule} ({digest}): {diagnostic}"}
                for expression, diagnostic in validations
            ],
        },
    }
