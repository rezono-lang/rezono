"""Render release-specific admission bindings for managed namespaces."""

import re


RULES = {"verified-supply", "in-zone-flow"}
MANAGED_NAMESPACE_LABEL = "rezono.dev/admission"


def render_binding(*, rule: str, digest: str, parameter_name: str) -> dict:
    if rule not in RULES:
        raise ValueError(f"Unsupported admission rule: {rule}")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected a lowercase SHA-256 publication digest")
    if (
        len(parameter_name) > 253
        or not all(
            re.fullmatch(r"[a-z0-9](?:[-a-z0-9]{0,61}[a-z0-9])?", label)
            for label in parameter_name.split(".")
        )
    ):
        raise ValueError("Expected a DNS subdomain parameter name")

    policy_name = f"{rule}.{digest[:32]}.{digest[32:]}"
    return {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "ValidatingAdmissionPolicyBinding",
        "metadata": {"name": f"binding.{policy_name}"},
        "spec": {
            "policyName": policy_name,
            "validationActions": ["Deny"],
            # Omitting namespace resolves the named parameter in the request namespace.
            "paramRef": {"name": parameter_name, "parameterNotFoundAction": "Deny"},
            "matchResources": {
                "namespaceSelector": {
                    "matchLabels": {MANAGED_NAMESPACE_LABEL: "enabled"},
                },
            },
        },
    }
