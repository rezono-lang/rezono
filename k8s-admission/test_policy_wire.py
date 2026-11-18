import pytest

from publication_wire_fixture import wire_case


@pytest.mark.xfail(strict=True, reason="Depends on the publication CRD and binding renderer. Implement the in-zone-flow policy renderer in k8s-admission/policy_renderer.py with the registered parameter type. Read decisions/k8s-admission-publication.md.")
def test_policy_and_binding_resolve_the_registered_parameter():
    resource, identity = wire_case()
    from bindings import render_binding
    from policy_renderer import render_policy

    rule = "in-zone-flow"
    digest = resource["spec"]["digest"]
    name = resource["metadata"]["name"]
    policy = render_policy(rule=rule, digest=digest)
    binding = render_binding(rule=rule, digest=digest, parameter_name=name)
    assert policy["apiVersion"] == "admissionregistration.k8s.io/v1"
    assert policy["kind"] == "ValidatingAdmissionPolicy"
    assert policy["spec"]["paramKind"] == identity
    assert binding["spec"]["policyName"] == policy["metadata"]["name"]
    assert binding["spec"]["paramRef"] == {"name": name, "parameterNotFoundAction": "Deny"}
