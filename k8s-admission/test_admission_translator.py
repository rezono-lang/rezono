"""Regression tests for soundness guards in admission_translator."""

import pytest

from admission_translator import _request_root_expression, translate
from translator_support import DIGEST, fixture, load_program, program

S = "string"
PAIR = [("ns", S), ("a", S)]
POD_MATCH = [
    {
        "apiGroups": [""],
        "apiVersions": ["v1"],
        "operations": ["CREATE"],
        "resources": ["pods"],
        "scope": "Namespaced",
    }
]


def _single_req_binding(rule_name, relation="req_a", col_names=("ns", "a"), parameters=None):
    return {
        "format": "rezono.admission-binding/1",
        "rule": rule_name,
        "output": "allow",
        "match": POD_MATCH,
        "request": [
            {
                "relation": relation,
                "each": [{"name": "c", "path": ["object", "spec", "containers"]}],
                "columns": {
                    col_names[0]: {"path": ["request", "namespace"]},
                    col_names[1]: {"path": ["c", "image"]},
                },
            }
        ],
        "parameters": parameters or {},
    }


def _two_req_binding(rule_name, parameters=None):
    return {
        "format": "rezono.admission-binding/1",
        "rule": rule_name,
        "output": "allow",
        "match": POD_MATCH,
        "request": [
            {
                "relation": "req_a",
                "each": [{"name": "c", "path": ["object", "spec", "containers"]}],
                "columns": {
                    "ns": {"path": ["request", "namespace"]},
                    "v": {"path": ["c", "image"]},
                },
            },
            {
                "relation": "req_b",
                "each": [{"name": "c", "path": ["object", "spec", "initContainers"], "optional": True}],
                "columns": {
                    "ns": {"path": ["request", "namespace"]},
                    "v": {"path": ["c", "image"]},
                },
            },
        ],
        "parameters": parameters or {},
    }


def test_refuses_self_join_on_same_request_relation():
    negated_self_join = program(
        {
            "req_a": ("base", PAIR),
            "conflict": ("derived", PAIR),
            "allow": ("derived", PAIR),
        },
        [
            (
                "conflict",
                ("conflict", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("req_a", ["?ns", "?b"], "positive")],
                [("ne", "?a", "?b")],
            ),
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("conflict", ["?ns", "?a"], "negative")],
                [],
            ),
        ],
    )
    with pytest.raises(ValueError, match="self-join"):
        translate(negated_self_join, _single_req_binding("self-join-neg"), DIGEST)

    positive_self_join = program(
        {
            "req_a": ("base", PAIR),
            "allow": ("derived", PAIR),
        },
        [
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("req_a", ["?ns", "?b"], "positive")],
                [("ne", "?a", "?b")],
            ),
        ],
    )
    with pytest.raises(ValueError, match="self-join"):
        translate(positive_self_join, _single_req_binding("self-join-pos"), DIGEST)


def test_refuses_derived_rule_reading_other_request_relation():
    pair_v = [("ns", S), ("v", S)]
    negated_other = program(
        {
            "req_a": ("base", pair_v),
            "req_b": ("base", pair_v),
            "blocked": ("derived", pair_v),
            "allow": ("derived", pair_v),
        },
        [
            ("blocked", ("blocked", ["?ns", "?v"]), [("req_b", ["?ns", "?v"], "positive")], []),
            (
                "allow_a",
                ("allow", ["?ns", "?v"]),
                [("req_a", ["?ns", "?v"], "positive"), ("blocked", ["?ns", "?v"], "negative")],
                [],
            ),
            ("allow_b", ("allow", ["?ns", "?v"]), [("req_b", ["?ns", "?v"], "positive")], []),
        ],
    )
    with pytest.raises(ValueError, match="request relation"):
        translate(negated_other, _two_req_binding("cross-req-neg"), DIGEST)

    disjunctive_other = program(
        {
            "req_a": ("base", pair_v),
            "req_b": ("base", pair_v),
            "ok_a": ("base", pair_v),
            "ok_b": ("base", pair_v),
            "allow": ("derived", pair_v),
        },
        [
            (
                "allow_a",
                ("allow", ["?ns", "?v"]),
                [("req_a", ["?ns", "?v"], "positive"), ("ok_a", ["?ns", "?v"], "positive")],
                [],
            ),
            (
                "allow_b",
                ("allow", ["?ns", "?v"]),
                [("req_b", ["?ns", "?v"], "positive"), ("ok_b", ["?ns", "?v"], "positive")],
                [],
            ),
        ],
    )
    params = {
        "ok_a": {"scope": "ns", "lists": [{"field": "okA", "columns": ["v"]}]},
        "ok_b": {"scope": "ns", "lists": [{"field": "okB", "columns": ["v"]}]},
    }
    with pytest.raises(ValueError, match="request relation"):
        translate(disjunctive_other, _two_req_binding("cross-req-disj", parameters=params), DIGEST)


def test_refuses_quantifying_over_other_rows_of_same_request_relation():
    bad_params = {"bad": {"scope": "ns", "lists": [{"field": "bad", "columns": ["a"]}]}}

    # Existential negation: has_bad(?ns) depends on whether ANY row in req_a is bad.
    existential_neg = program(
        {
            "req_a": ("base", PAIR),
            "bad": ("base", PAIR),
            "has_bad": ("derived", [("ns", S)]),
            "allow": ("derived", PAIR),
        },
        [
            (
                "has_bad",
                ("has_bad", ["?ns"]),
                [("req_a", ["?ns", "?img"], "positive"), ("bad", ["?ns", "?img"], "positive")],
                [],
            ),
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("has_bad", ["?ns"], "negative")],
                [],
            ),
        ],
    )
    with pytest.raises(ValueError, match="other rows"):
        translate(existential_neg, _single_req_binding("existential-neg", parameters=bad_params), DIGEST)

    # Constant-matched existential negation: has_root(?ns) checks whether another row has "root".
    const_existential_neg = program(
        {
            "req_a": ("base", PAIR),
            "has_root": ("derived", [("ns", S)]),
            "allow": ("derived", PAIR),
        },
        [
            ("has_root", ("has_root", ["?ns"]), [("req_a", ["?ns", "root"], "positive")], []),
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("has_root", ["?ns"], "negative")],
                [],
            ),
        ],
    )
    with pytest.raises(ValueError, match="other rows"):
        translate(const_existential_neg, _single_req_binding("const-existential-neg"), DIGEST)

    # Same-arity negated derived relation queried at a different row (?other != ?a).
    companion_params = {
        "bad": {"scope": "ns", "lists": [{"field": "bad", "columns": ["a"]}]},
        "companion": {"scope": "ns", "lists": [{"field": "companions", "columns": ["a", "other"]}]},
    }
    different_target_neg = program(
        {
            "req_a": ("base", PAIR),
            "bad": ("base", PAIR),
            "companion": ("base", [("ns", S), ("a", S), ("other", S)]),
            "blocked": ("derived", PAIR),
            "allow": ("derived", PAIR),
        },
        [
            (
                "blocked",
                ("blocked", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("bad", ["?ns", "?a"], "positive")],
                [],
            ),
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [
                    ("req_a", ["?ns", "?a"], "positive"),
                    ("companion", ["?ns", "?a", "?other"], "positive"),
                    ("blocked", ["?ns", "?other"], "negative"),
                ],
                [],
            ),
        ],
    )
    with pytest.raises(ValueError, match="other rows"):
        translate(different_target_neg, _single_req_binding("diff-target-neg", parameters=companion_params), DIGEST)

    # Positive rule quantifying over another row of the same request relation.
    pair_params = {"pair_ok": {"scope": "ns", "lists": [{"field": "pairs", "columns": ["a", "b"]}]}}
    positive_other_row = program(
        {
            "req_a": ("base", PAIR),
            "pair_ok": ("base", [("ns", S), ("a", S), ("b", S)]),
            "allow": ("derived", PAIR),
        },
        [
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?b"], "positive"), ("pair_ok", ["?ns", "?a", "?b"], "positive")],
                [],
            ),
        ],
    )
    with pytest.raises(ValueError, match="other rows"):
        translate(positive_other_row, _single_req_binding("pos-other-row", parameters=pair_params), DIGEST)


def test_allows_negated_derived_relation_matching_current_row():
    bad_params = {"bad": {"scope": "ns", "lists": [{"field": "bad", "columns": ["a"]}]}}
    same_row_neg = program(
        {
            "req_a": ("base", PAIR),
            "bad": ("base", PAIR),
            "blocked": ("derived", PAIR),
            "allow": ("derived", PAIR),
        },
        [
            (
                "blocked",
                ("blocked", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("bad", ["?ns", "?a"], "positive")],
                [],
            ),
            (
                "allow",
                ("allow", ["?ns", "?a"]),
                [("req_a", ["?ns", "?a"], "positive"), ("blocked", ["?ns", "?a"], "negative")],
                [],
            ),
        ],
    )
    policy = translate(same_row_neg, _single_req_binding("same-row-neg", parameters=bad_params), DIGEST)
    violation_expr = policy["spec"]["validations"][2]["expression"]
    assert "params.spec.bad" in violation_expr
    assert "!(false)" not in violation_expr


def test_request_root_expression_guards_more_than_four_keys():
    fields = ["name", "namespace", "operation", "subResource", "uid"]
    binding_five = {
        "request": [
            {
                "relation": "req",
                "each": [],
                "columns": {field: {"path": ["request", field]} for field in fields},
            }
        ]
    }
    expr = _request_root_expression(binding_five)
    for field in fields:
        assert f"has(request.{field})" in expr

    nine_fields = [f"f{i}" for i in range(9)]
    binding_nine = {
        "request": [
            {
                "relation": "req",
                "each": [],
                "columns": {field: {"path": ["request", field]} for field in nine_fields},
            }
        ]
    }
    with pytest.raises(ValueError, match="guarded request fields"):
        _request_root_expression(binding_nine)


def test_reference_policies_translate_cleanly():
    for rule_name in ("verified-supply", "in-zone-flow"):
        prog = load_program(f"{rule_name}.rules.yaml")
        binding = fixture(f"{rule_name}.binding.yaml")
        policy = translate(prog, binding, DIGEST)
        assert policy["kind"] == "ValidatingAdmissionPolicy"
        assert policy["metadata"]["name"].startswith(f"{rule_name}.")
        assert len(policy["spec"]["variables"]) == 1
        assert len(policy["spec"]["validations"]) == 3
