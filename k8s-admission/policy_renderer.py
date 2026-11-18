"""Render the in-zone flow policy for the registered namespace publication."""

import re


_LABEL = "'rezono.org/service'"


def _exact_selector(selector: str) -> str:
    return (
        f"has({selector}.matchLabels) && size({selector}.matchLabels) == 1 && "
        f"{_LABEL} in {selector}.matchLabels && {selector}.matchLabels[{_LABEL}] != '' && "
        f"(!has({selector}.matchExpressions) || size({selector}.matchExpressions) == 0)"
    )


def _direction(field: str, peer_field: str, source: str, destination: str) -> str:
    rules = f"object.spec.{field}"
    policy_type = field.capitalize()
    peer = f"rule.{peer_field}"
    return (
        f"!has({rules}) || size({rules}) == 0 || "
        f"('{policy_type}' in object.spec.policyTypes && {rules}.all(rule, "
        f"has({peer}) && size({peer}) > 0 && has(rule.ports) && size(rule.ports) > 0 && "
        f"{peer}.all(peer, has(peer.podSelector) && !has(peer.namespaceSelector) && !has(peer.ipBlock) && "
        f"{_exact_selector('peer.podSelector')} && rule.ports.all(p, "
        "(!has(p.protocol) || p.protocol == 'TCP') && has(p.port) && type(p.port) == int && "
        "int(p.port) >= 1 && int(p.port) <= 65535 && "
        "(!has(p.endPort) || (p.endPort >= int(p.port) && p.endPort <= 65535)) && "
        f"size(params.spec.flows.filter(f, f.source == {source} && f.destination == {destination} && "
        "f.port >= int(p.port) && f.port <= (has(p.endPort) ? p.endPort : int(p.port)))) "
        "== (has(p.endPort) ? p.endPort - int(p.port) + 1 : 1)))))"
    )


def render_policy(*, rule: str, digest: str) -> dict:
    """Build a fail-closed Kubernetes policy for one verified publication release."""
    if rule != "in-zone-flow":
        raise ValueError(f"Unsupported admission rule: {rule}")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Expected a lowercase SHA-256 publication digest")

    selector = "object.spec.podSelector"
    local = f"{selector}.matchLabels[{_LABEL}]"
    peer = f"peer.podSelector.matchLabels[{_LABEL}]"
    no_rules = (
        "(!has(object.spec.ingress) || size(object.spec.ingress) == 0) && "
        "(!has(object.spec.egress) || size(object.spec.egress) == 0)"
    )
    baseline = (
        f"(!has({selector}.matchLabels) || size({selector}.matchLabels) == 0) && "
        f"(!has({selector}.matchExpressions) || size({selector}.matchExpressions) == 0) && "
        "size(object.spec.policyTypes) == 2 && "
        "'Ingress' in object.spec.policyTypes && 'Egress' in object.spec.policyTypes && "
        f"{no_rules}"
    )
    ingress = _direction("ingress", "from", peer, local)
    egress = _direction("egress", "to", local, peer)
    valid_target = (
        "has(object.spec.policyTypes) && size(object.spec.policyTypes) > 0 && "
        "object.spec.policyTypes.all(t, t in ['Ingress', 'Egress']) && "
        f"(variables.baseline || ({_exact_selector(selector)}))"
    )
    validations = [
        (
            f"params.spec.digest == '{digest}'",
            "publication digest does not match the policy release",
        ),
        (
            "variables.validTarget",
            "missing or unsupported service selection or policy types",
        ),
        (
            f"!variables.validTarget || variables.baseline || (({ingress}) && ({egress}))",
            "grant exceeds published same-namespace TCP flows",
        ),
    ]
    return {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "ValidatingAdmissionPolicy",
        "metadata": {"name": f"{rule}.{digest[:32]}.{digest[32:]}"},
        "spec": {
            "failurePolicy": "Fail",
            "paramKind": {"apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication"},
            "matchConstraints": {
                "resourceRules": [{
                    "apiGroups": ["networking.k8s.io"],
                    "apiVersions": ["v1"],
                    "operations": ["CREATE", "UPDATE"],
                    "resources": ["networkpolicies"],
                    "scope": "Namespaced",
                }],
            },
            "variables": [
                {"name": "baseline", "expression": f"has(object.spec.policyTypes) && ({baseline})"},
                {"name": "validTarget", "expression": valid_target},
            ],
            "validations": [
                {"expression": expression, "message": f"{rule} ({digest}): {diagnostic}"}
                for expression, diagnostic in validations
            ],
        },
    }
