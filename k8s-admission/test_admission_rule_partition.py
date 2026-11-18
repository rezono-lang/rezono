"""The admission compiler separates typed request rows from model projections.

See decisions/k8s-admission-rules.md for the split and the one-object boundary.
"""

import pytest

from rezono_compiler import batch, rules


KEY = ("namespace", "service", "image")
POD = ("sample", "web", "registry.example.org/sample/app@sha256:" + "a" * 64)
OTHER_NAMESPACE = ("other", *POD[1:])
OTHER_SERVICE = (POD[0], "api", POD[2])
OTHER_IMAGE = (*POD[:2], "registry.example.org/sample/app@sha256:" + "b" * 64)
MODEL_ROWS = {
    "image_build": [POD, OTHER_NAMESPACE, OTHER_IMAGE],
    "image_signature": [POD, OTHER_SERVICE],
}


def program_for(*request_relations):
    names = ("image_build", "image_signature", "verified_image", *request_relations, "allow_image")
    projections = {"verified_image", "allow_image"}
    columns = [{"name": column, "type": "string"} for column in KEY]
    terms = ["?" + column for column in KEY]

    def rule(head, premises):
        return {
            "id": head,
            "module": "sample",
            "stratum": "1",
            "head": {"relation": head, "terms": terms},
            "body": [
                {"relation": relation, "terms": terms, "polarity": "positive",
                 "stratum": "1" if relation in projections else "0"}
                for relation in premises
            ],
            "origin": {"file": "sample.dl", "line": "1"},
        }

    return rules.load({
        "format": rules.FORMAT,
        "pack": "admission_sample",
        "relations": [
            {"name": name, "key": columns, "role": "derived", "module": "sample"}
            if name in projections else {"name": name, "key": columns, "role": "base"}
            for name in names
        ],
        "rules": [
            rule("verified_image", ("image_build", "image_signature")),
            rule("allow_image", ("verified_image", *request_relations)),
        ],
    }, require_witness=False)


def evaluate(program, rows, relation):
    with batch.connect(program, rows, threads=1) as connection:
        batch.compute(connection, program)
        return batch.read(connection, program, [relation])[relation]


def test_partition_typed_admission_rule():
    source = program_for("pod_image")
    cases = [(POD, True), (OTHER_NAMESPACE, False), (OTHER_SERVICE, False), (OTHER_IMAGE, False)]
    baseline = evaluate(source, MODEL_ROWS, "verified_image")
    assert baseline == {POD}
    for row, allowed in cases:
        assert evaluate(source, {**MODEL_ROWS, "pod_image": [row]}, "allow_image") == (
            {row} if allowed else set()
        )

    from admission_rule_partition import partition_rule

    model, request = partition_rule(source, "allow_image", request_objects={"pod_image": "Pod"})
    assert "pod_image" not in model.relations
    assert set(request.relations) == {"pod_image", "verified_image", "allow_image"}
    assert request.relations["verified_image"].role == "base"
    assert tuple(column.name for column in request.relations["verified_image"].key) == KEY
    assert evaluate(model, MODEL_ROWS, "verified_image") == baseline
    for row, allowed in cases:
        assert evaluate(request, {"verified_image": baseline, "pod_image": [row]}, "allow_image") == (
            {row} if allowed else set()
        )

    two_objects = program_for("pod_image", "config_image")
    with pytest.raises(ValueError, match="one incoming object"):
        partition_rule(
            two_objects,
            "allow_image",
            request_objects={"pod_image": "Pod", "config_image": "ConfigMap"},
        )
