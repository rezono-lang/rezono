"""The supply rule covers the native Pod API and its image-bearing update path."""

import pytest


def test_supply_policy_covers_pods_and_ephemeral_container_updates():
    from supply_policy import render_supply_policy

    policy = render_supply_policy(digest="d" * 64)
    assert policy["kind"] == "ValidatingAdmissionPolicy"
    spec = policy["spec"]
    assert spec["paramKind"] == {"apiVersion": "admission.rezono.org/v1alpha1",
                                 "kind": "NamespacePublication"}
    assert spec["failurePolicy"] == "Fail"
    rules = spec["matchConstraints"]["resourceRules"]
    pairs = {(resource, operation) for rule in rules
             for resource in rule["resources"] for operation in rule["operations"]}
    assert {("pods", "CREATE"), ("pods", "UPDATE"), ("pods/ephemeralcontainers", "UPDATE")} <= pairs
    assert all(rule["apiGroups"] == [""] and rule["apiVersions"] == ["v1"] for rule in rules)
    assert spec["validations"] and all(v.get("expression") for v in spec["validations"])
