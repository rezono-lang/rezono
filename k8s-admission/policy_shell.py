"""Build the ValidatingAdmissionPolicy shell around translated CEL expressions.

See decisions/k8s-admission-translator.md, "Policy shell".
"""

from copy import deepcopy
import re

_DIGEST_RE = re.compile(r"[0-9a-f]{64}")
_RULE_RE = re.compile(r"[a-z0-9](?:[-a-z0-9]*[a-z0-9])?")


def policy_shell(binding: dict, digest: str, *, missing: str, violation: str) -> dict:
    """Wrap translated `missing` and `violation` CEL expressions in a ValidatingAdmissionPolicy."""
    if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
        raise ValueError("Expected a lowercase SHA-256 publication digest")
    rule = binding.get("rule")
    if not isinstance(rule, str) or _RULE_RE.fullmatch(rule) is None:
        raise ValueError(f"Invalid admission rule identity: {rule!r}")

    prefix = f"{rule} ({digest}): "
    validations = [
        (
            f"params.spec.digest == '{digest}'",
            "publication digest does not match the policy release",
        ),
        (
            "!variables.missing",
            "missing or unsupported input",
        ),
        (
            f"variables.missing || ({violation})",
            "request exceeds the published rule",
        ),
    ]
    return {
        "apiVersion": "admissionregistration.k8s.io/v1",
        "kind": "ValidatingAdmissionPolicy",
        "metadata": {"name": f"{rule}.{digest[:32]}.{digest[32:]}"},
        "spec": {
            "failurePolicy": "Fail",
            "paramKind": {
                "apiVersion": "admission.rezono.org/v1alpha1",
                "kind": "NamespacePublication",
            },
            "matchConstraints": {
                "resourceRules": deepcopy(binding["match"]),
            },
            "variables": [{"name": "missing", "expression": missing}],
            "validations": [
                {"expression": expression, "message": prefix + diagnostic}
                for expression, diagnostic in validations
            ],
        },
    }
