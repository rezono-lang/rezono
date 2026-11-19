"""The partition names what a refused admission rule reads.

See decisions/k8s-admission-translator.md, "What CEL cannot do", for the exact message.
"""

import pytest
from translator_support import load_program, program

S = "string"
KEY = [("namespace", S), ("service", S)]


@pytest.mark.xfail(
    strict=True,
    reason="Name each request relation and its object kind in partition_rule's refusal, as "
           "decisions/k8s-admission-translator.md specifies under What CEL cannot do. "
           "Write in k8s-admission/admission_rule_partition.py.",
)
def test_partition_diagnostic():
    from admission_rule_partition import partition_rule

    joined = program(
        {"pod_label": ("base", KEY), "config_label": ("base", KEY), "unused": ("base", KEY),
         "allow": ("derived", KEY)},
        [("allow", ("allow", ["?n", "?s"]),
          [("pod_label", ["?n", "?s"], "positive"), ("config_label", ["?n", "?s"], "positive")], [])],
    )
    objects = {"pod_label": "Pod", "config_label": "ConfigMap", "unused": "Secret"}
    with pytest.raises(ValueError) as refused:
        partition_rule(joined, "allow", request_objects=objects)
    assert str(refused.value) == (
        "allow: admission requires one incoming object; it reads config_label (ConfigMap), pod_label (Pod)"
    )

    supply = load_program("verified-supply.rules.yaml")
    with pytest.raises(ValueError) as none:
        partition_rule(supply, "verified_image", request_objects={"pod_image": "Pod"})
    assert str(none.value) == "verified_image: admission requires one incoming object; it reads none"

    model, request = partition_rule(supply, "allow_image", request_objects={"pod_image": "Pod", "unused": "Secret"})
    assert "pod_image" in request.relations and "pod_image" not in model.relations
