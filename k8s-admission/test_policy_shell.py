"""The generated policy keeps the identity, matching and failure mode of the hand-written part 1 policies.

See decisions/k8s-admission-translator.md, "Policy shell". Part 1's policy_renderer is the expectation for
everything that does not depend on the translated expressions.
"""

import pytest
from translator_support import DIGEST, fixture

MISSING = "object.spec.containers.exists(c, !has(c.image))"
VIOLATION = "object.spec.containers.all(c, c.image in ['a'])"


@pytest.mark.xfail(
    strict=True,
    reason="Write policy_shell.policy_shell as decisions/k8s-admission-translator.md specifies under Policy shell. "
           "Write in k8s-admission/policy_shell.py.",
)
def test_policy_shell():
    from policy_renderer import render_policy
    from policy_shell import policy_shell

    for rule in ("verified-supply", "in-zone-flow"):
        binding = fixture(f"{rule}.binding.yaml")
        shell = policy_shell(binding, DIGEST, missing=MISSING, violation=VIOLATION)
        manual = render_policy(rule=rule, digest=DIGEST)
        assert shell["metadata"] == manual["metadata"]
        for field in ("failurePolicy", "paramKind", "matchConstraints"):
            assert shell["spec"][field] == manual["spec"][field], (rule, field)
        assert shell["spec"]["validations"][0] == manual["spec"]["validations"][0]
        prefix = f"{rule} ({DIGEST}): "
        assert shell == {
            "apiVersion": "admissionregistration.k8s.io/v1",
            "kind": "ValidatingAdmissionPolicy",
            "metadata": {"name": f"{rule}.{DIGEST[:32]}.{DIGEST[32:]}"},
            "spec": {
                "failurePolicy": "Fail",
                "paramKind": {"apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication"},
                "matchConstraints": {"resourceRules": binding["match"]},
                "variables": [{"name": "missing", "expression": MISSING}],
                "validations": [
                    {"expression": f"params.spec.digest == '{DIGEST}'",
                     "message": prefix + "publication digest does not match the policy release"},
                    {"expression": "!variables.missing", "message": prefix + "missing or unsupported input"},
                    {"expression": f"variables.missing || ({VIOLATION})",
                     "message": prefix + "request exceeds the published rule"},
                ],
            },
        }

    binding = fixture("verified-supply.binding.yaml")
    for digest in (DIGEST.upper(), DIGEST[:63], DIGEST + "0"):
        with pytest.raises(ValueError):
            policy_shell(binding, digest, missing=MISSING, violation=VIOLATION)
    for rule in ("Verified-Supply", "verified supply", "-supply", ""):
        with pytest.raises(ValueError):
            policy_shell(dict(binding, rule=rule), DIGEST, missing=MISSING, violation=VIOLATION)
