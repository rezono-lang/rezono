"""The translator's checked-in programs and bindings agree with the hand-calculated part 1 cases.

The cases are those of decisions/k8s-admission-rules.md, "Hand-calculated fixtures".
"""

from translator_support import (
    IMAGE_A,
    IMAGE_B,
    IMAGE_C,
    evaluate,
    fixture,
    load_program,
)


def admitted(prog, model_rows, request, rows, output):
    allowed = evaluate(prog, {**model_rows, request: rows}, output)
    return all(tuple(str(value) for value in row) in allowed for row in rows)


def test_supply_program_matches_the_hand_calculated_pods():
    prog = load_program("verified-supply.rules.yaml")
    published = [("sample", "web", IMAGE_A), ("sample", "web", IMAGE_B)]
    model = {"image_build": published, "image_signature": published}
    cases = [
        ([IMAGE_A], "sample", True),
        ([IMAGE_A, IMAGE_B], "sample", True),
        ([IMAGE_C], "sample", False),
        ([IMAGE_A, IMAGE_C], "sample", False),
        ([IMAGE_A], "other", False),
    ]
    for images, namespace, expected in cases:
        rows = [(namespace, "web", image) for image in images]
        assert admitted(prog, model, "pod_image", rows, "allow_image") is expected, (images, namespace)
    unsigned = {"image_build": published, "image_signature": published[:1]}
    assert not admitted(prog, unsigned, "pod_image", [("sample", "web", IMAGE_B)], "allow_image")


def test_flow_program_matches_the_hand_calculated_policies():
    prog = load_program("in-zone-flow.rules.yaml")
    model = {"admission_flow": [("sample", "reader", "web", "TCP", 443), ("sample", "probe", "web", "TCP", 8443)]}
    cases = [
        ([("reader", 443)], True),
        ([("probe", 8443)], True),
        ([("reader", 8443)], False),
        ([("reader", 443), ("reader", 8443), ("probe", 443), ("probe", 8443)], False),
    ]
    for requested, expected in cases:
        rows = [("sample", source, "web", "TCP", port) for source, port in requested]
        assert admitted(prog, model, "requested_flow", rows, "allow_flow") is expected, requested
    assert not admitted(prog, model, "requested_flow", [("sample", "reader", "web", "UDP", 443)], "allow_flow")


def test_bindings_name_the_program_columns():
    for rule in ("verified-supply", "in-zone-flow"):
        prog = load_program(f"{rule}.rules.yaml")
        binding = fixture(f"{rule}.binding.yaml")
        assert binding["format"] == "rezono.admission-binding/1"
        assert binding["rule"] == rule
        assert prog.relations[binding["output"]].role == "derived"
        requested = {source["relation"] for source in binding["request"]}
        for source in binding["request"]:
            relation = prog.relations[source["relation"]]
            assert relation.role == "base"
            assert list(source["columns"]) == [column.name for column in relation.key]
        for name, parameter in binding["parameters"].items():
            assert name not in requested
            columns = [column.name for column in prog.relations[name].key]
            assert parameter["scope"] in columns
            for entry in parameter["lists"]:
                assert set(entry["columns"]) | set(entry.get("fixed", {})) == set(columns) - {parameter["scope"]}
