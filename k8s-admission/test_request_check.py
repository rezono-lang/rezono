"""The request side of an admission binding agrees with its rule program.

See decisions/k8s-admission-binding-checks.md, "Request check". Each case changes a checked-in binding in one
place; the expected problems follow by hand from that decision, including the problems one change causes
further on, such as a column that reads from a renamed iterator.
"""

from copy import deepcopy

import pytest


def ingress(doc):
    return doc["request"][0]


def egress(doc):
    return doc["request"][1]


def swap_first_iterators(doc):
    each = ingress(doc)["each"]
    each[0], each[1] = each[1], each[0]


# (case, change, expected problems in sorted order)
CASES = [
    ("unknown output", lambda d: d.update(output="allow_flows"), [("unknown_relation", "output")]),
    ("base output", lambda d: d.update(output="requested_flow"), [("output_role", "output")]),
    ("derived request relation", lambda d: ingress(d).update(relation="published_flow"),
     [("request_role", "request/0/relation")]),
    ("unknown request relation: no column codes", lambda d: egress(d).update(relation="flow", columns={"x": {
        "path": ["object", "spec"]}}),
     [("unknown_relation", "request/1/relation")]),
    ("repeated iterator name breaks the column that read it", lambda d: ingress(d)["each"][1].update(name="rule"),
     [("iterator_name", "request/0/each/1/name"), ("path_root", "request/0/columns/source/path")]),
    ("reserved iterator name", lambda d: ingress(d)["each"][0].update(name="object"),
     [("iterator_name", "request/0/each/0/name"), ("path_root", "request/0/each/1/path"),
      ("path_root", "request/0/each/2/path")]),
    ("iterator read before it is defined", swap_first_iterators, [("path_root", "request/0/each/0/path")]),
    ("column reads an unknown root", lambda d: egress(d)["columns"]["namespace"].update(
        path=["policy", "metadata", "namespace"]), [("path_root", "request/1/columns/namespace/path")]),
    ("range end reads an unknown root", lambda d: ingress(d)["columns"]["port"].update(end=["ports", "endPort"]),
     [("path_root", "request/0/columns/port/end")]),
    ("extra column", lambda d: ingress(d)["columns"].update(zone={"path": ["object", "metadata", "name"]}),
     [("column_unknown", "request/0/columns/zone")]),
    ("missing column", lambda d: egress(d)["columns"].pop("protocol"), [("column_missing", "request/1/columns/protocol")]),
    ("port range on text", lambda d: ingress(d)["columns"]["protocol"].update(reading="port-range"),
     [("reading_type", "request/0/columns/protocol/reading")]),
    ("integer default for text", lambda d: ingress(d)["columns"]["protocol"].update(default=6),
     [("default_type", "request/0/columns/protocol/default")]),
    ("text default for an integer", lambda d: ingress(d)["columns"]["port"].update(default="443"),
     [("default_type", "request/0/columns/port/default")]),
    ("boolean default for an integer", lambda d: ingress(d)["columns"]["port"].update(default=True),
     [("default_type", "request/0/columns/port/default")]),
    ("integer default for an integer", lambda d: ingress(d)["columns"]["port"].update(default=443), []),
    ("every source is checked", lambda d: [s["columns"].update(zone={"path": ["object", "kind"]}) for s in d["request"]],
     [("column_unknown", "request/0/columns/zone"), ("column_unknown", "request/1/columns/zone")]),
]


@pytest.mark.xfail(
    strict=True,
    reason="extra: Write request_check.check_request as decisions/k8s-admission-binding-checks.md specifies under "
           "Request check. Write in k8s-admission/request_check.py.",
)
def test_request_check():
    from request_check import check_request
    from translator_support import fixture, load_program

    for rule in ("verified-supply", "in-zone-flow"):
        assert check_request(fixture(f"{rule}.binding.yaml"), load_program(f"{rule}.rules.yaml")) == [], rule

    program = load_program("in-zone-flow.rules.yaml")
    original = fixture("in-zone-flow.binding.yaml")
    for case, change, expected in CASES:
        binding = deepcopy(original)
        change(binding)
        assert check_request(binding, program) == expected, case
    assert original == fixture("in-zone-flow.binding.yaml")
