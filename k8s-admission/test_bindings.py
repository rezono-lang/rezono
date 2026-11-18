"""Release identity and fail-closed binding for a single namespace publication."""

import re

import pytest


def test_bindings_deny_missing_namespace_parameters():
    from bindings import render_binding

    for rule in ("verified-supply", "in-zone-flow"):
        for digest in ("a" * 64, "b" * 64):
            parameter = "release-" + digest[:32] + "." + digest[32:]
            binding = render_binding(rule=rule, digest=digest, parameter_name=parameter)
            assert binding["apiVersion"] == "admissionregistration.k8s.io/v1"
            assert binding["kind"] == "ValidatingAdmissionPolicyBinding"
            spec = binding["spec"]
            assert spec["validationActions"] == ["Deny"]
            assert spec["paramRef"] == {"name": parameter, "parameterNotFoundAction": "Deny"}
            for name in (binding["metadata"]["name"], spec["policyName"]):
                assert rule in name
                # A DNS label has a 63-character limit. Splitting the digest
                # across labels retains every digit in an API-generated error.
                assert digest in name.replace(".", "").replace("-", "")
                assert len(name) <= 253
                assert all(re.fullmatch(r"[a-z0-9]([-a-z0-9]{0,61}[a-z0-9])?", label)
                           for label in name.split("."))
            assert spec["matchResources"]["namespaceSelector"]
