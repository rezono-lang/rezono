"""The parameter side of an admission binding agrees with its rule program.

See decisions/k8s-admission-binding-checks.md, "Parameter check". Each case changes a checked-in binding in one
place; the expected problems follow by hand from that decision. The two shadowing cases are each other's
counter-case: the same two lists are sound in one order and not in the other.
"""

from copy import deepcopy

import pytest

P = "parameters/published_flow"


def published(doc):
    return doc["parameters"]["published_flow"]


def lists(doc):
    return published(doc)["lists"]


def rename(doc):
    entry = published(doc)
    entry["scope"] = "zone"
    doc["parameters"] = {"unknown_flow": entry}


def also_request(doc):
    doc["parameters"]["requested_flow"] = deepcopy(published(doc))


def swap_lists(doc):
    lists(doc).reverse()


# (case, change, expected problems in sorted order)
CASES = [
    ("unknown relation: nothing else", rename, [("unknown_relation", "parameters/unknown_flow")]),
    ("request relation published too", also_request,
     [("field_repeated", "parameters/requested_flow/lists/0/field"),
      ("field_repeated", "parameters/requested_flow/lists/1/field"),
      ("request_relation", "parameters/requested_flow")]),
    ("unknown scope leaves the namespace unwritten", lambda d: published(d).update(scope="zone"),
     [("list_cover", f"{P}/lists/0"), ("list_cover", f"{P}/lists/1"), ("scope_column", f"{P}/scope")]),
    ("unknown written column", lambda d: lists(d)[0].update(columns=["source", "destination", "port", "zone"]),
     [("list_column", f"{P}/lists/0/columns/3")]),
    ("scope written", lambda d: lists(d)[1].update(columns=["namespace", "source", "destination", "protocol", "port"]),
     [("list_column", f"{P}/lists/1/columns/0")]),
    ("unknown fixed column", lambda d: lists(d)[0].update(fixed={"protocol": "TCP", "zone": "a"}),
     [("fixed_column", f"{P}/lists/0/fixed/zone")]),
    ("scope fixed", lambda d: lists(d)[0].update(fixed={"protocol": "TCP", "namespace": "blue"}),
     [("fixed_column", f"{P}/lists/0/fixed/namespace")]),
    ("written column fixed", lambda d: lists(d)[1].update(fixed={"protocol": "UDP"}),
     [("fixed_column", f"{P}/lists/1/fixed/protocol")]),
    ("integer fixed for text", lambda d: lists(d)[0].update(fixed={"protocol": 6}),
     [("fixed_type", f"{P}/lists/0/fixed/protocol")]),
    ("protocol neither written nor fixed", lambda d: lists(d)[0].pop("fixed"),
     [("list_cover", f"{P}/lists/0"), ("list_shadowed", f"{P}/lists/1")]),
    ("catch-all list first", swap_lists, [("list_shadowed", f"{P}/lists/1")]),
    ("same field twice", lambda d: lists(d)[1].update(field="flows"), [("field_repeated", f"{P}/lists/1/field")]),
]


def test_parameter_check():
    from parameter_check import check_parameters
    from translator_support import fixture, load_program

    for rule in ("verified-supply", "in-zone-flow"):
        assert check_parameters(fixture(f"{rule}.binding.yaml"), load_program(f"{rule}.rules.yaml")) == [], rule

    program = load_program("in-zone-flow.rules.yaml")
    original = fixture("in-zone-flow.binding.yaml")
    for case, change, expected in CASES:
        binding = deepcopy(original)
        change(binding)
        assert check_parameters(binding, program) == expected, case

    supply = fixture("verified-supply.binding.yaml")
    supply["parameters"]["image_build"] = deepcopy(supply["parameters"]["verified_image"])
    assert check_parameters(supply, load_program("verified-supply.rules.yaml")) == [
        ("field_repeated", "parameters/image_build/lists/0/field")]
