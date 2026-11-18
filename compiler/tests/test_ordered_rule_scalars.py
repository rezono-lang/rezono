"""Exact comparisons of two independently recorded scalar values."""

from hashlib import sha256
from itertools import product
import json

import pytest

from contracts.validate import validator
from rezono_checker.canon import encode_key
from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, explain, rules


PREFIX = "2024-02-29T12:00:00"
DIGITS = "0" * 120
COMPARISONS = {
    -1: {"lt", "le", "ne"},
    0: {"eq", "le", "ge"},
    1: {"gt", "ge", "ne"},
    None: set(),
}
# Expected signs are authored separately from the engine. Invalid or missing values decide no test.
CASES = (
    ("utc_instant", "precision", f"{PREFIX}.{DIGITS}1Z", f"{PREFIX}.{DIGITS}2Z", -1),
    ("utc_instant", "same_fraction", f"{PREFIX}.{DIGITS}1Z", f"{PREFIX}.{DIGITS}100Z", 0),
    ("utc_instant", "whole_second", f"{PREFIX}Z", f"{PREFIX}.0Z", 0),
    ("utc_instant", "leap_boundary", "2024-02-29T23:59:59.9Z", "2024-03-01T00:00:00Z", -1),
    ("utc_instant", "invalid_leap_day", "2023-02-29T12:00:00Z", "2023-02-29T12:00:00Z", None),
    ("utc_instant", "invalid_offset", f"{PREFIX}+00:00", f"{PREFIX}+00:00", None),
    ("utc_instant", "invalid_second", "2024-02-29T12:00:60Z", f"{PREFIX}Z", None),
    ("utc_instant", "missing_operand", f"{PREFIX}Z", None, None),
    ("binary_text", "prefix", "alpha", "alpha-next", -1),
    ("binary_text", "different_utf8", "\ue000", "\U00010000", -1),
    ("binary_text", "distinct_spelling", "é", "e\u0301", 1),
    ("binary_text", "same_text", "alpha", "alpha", 0),
)


def program():
    def keys(*names):
        return [{"name": name, "type": "string"} for name in names]

    comparisons = sorted(COMPARISONS[-1] | COMPARISONS[0] | COMPARISONS[1])
    result = []
    for mode, op in product(("binary_text", "utc_instant"), comparisons):
        identifier = f"{mode}_{op}"
        result.append({
            "id": identifier, "module": "order", "stratum": "1",
            "head": {"relation": "comparison", "terms": [mode, "?case", op]},
            "body": [
                {"relation": "left_value", "terms": [mode, "?case", "?left"], "polarity": "positive", "stratum": "0"},
                {"relation": "right_value", "terms": [mode, "?case", "?right"], "polarity": "positive", "stratum": "0"},
            ],
            "conditions": [{"op": op, "left": "?left", "right": "?right", "compare_as": mode}],
            "witness": {"relation": f"{identifier}__witness", "variables": ["?case", "?left", "?right"]},
            "origin": {"file": "rules/order.dl", "line": str(len(result) + 1)},
        })
    return {"format": "rezono.rules/1", "pack": "ordered-scalars", "rules": result, "relations": [
        {"name": "left_value", "role": "base", "key": keys("mode", "case", "value")},
        {"name": "right_value", "role": "base", "key": keys("mode", "case", "value")},
        {"name": "comparison", "role": "derived", "module": "order", "explain": "materialize",
         "key": keys("mode", "case", "operator")},
    ]}


def manifest(snapshots):
    return {"id": "m-1", "snapshots": [
        {"relation": name, "role": "all", "complete": True, "uri": name, "format": "json",
         "sha256": sha256(data).hexdigest()}
        for name, data in sorted(snapshots.items())
    ]}


def test_ordered_rule_scalars_compiler_preserves_exact_values():
    doc = program()
    errors = validator("rules.yaml").validate(doc, "RuleProgram").results
    assert not errors, [error.message for error in errors]
    compiled = rules.load(doc)
    sources = {
        "left_value": [(mode, case, left) for mode, case, left, _, _ in CASES],
        "right_value": [(mode, case, right) for mode, case, _, right, _ in CASES if right is not None],
    }
    expected = {(mode, case, op) for mode, case, _, _, sign in CASES for op in COMPARISONS[sign]}
    with batch.connect(compiled, sources) as connection:
        batch.compute(connection, compiled, witnesses=True)
        results = batch.read(connection, compiled)
        assert results == {"comparison": expected}
        explainer = explain.Explainer(compiled, results | sources, batch.witnesses(connection, compiled))
        snapshots = {name: explainer.snapshot(name).encode() for name in compiled.relations}
    checked = load_rules(doc)
    for mode, case, left, right, sign in CASES:
        operation = {0: "eq", -1: "lt", 1: "gt"}.get(sign)
        if operation is None:
            continue
        proof = explainer.proof("comparison", (mode, case, operation), "m-1")
        witness, = proof["witnesses"]
        assert {binding["variable"]: binding["value"] for binding in witness["bindings"]} == {
            "?case": case, "?left": left, "?right": right,
        }
        report = check(proof, manifest(snapshots), checked, snapshots.__getitem__)
        assert report["valid"] and not report["findings"], (case, report)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Requires independent checker semantics for Condition.compare_as, including malformed UTC and byte order. "
    "Read decisions/ordered-rule-scalars.md."))
def test_ordered_rule_scalars_checker_recomputes_raw_operands():
    definitions = load_rules(program())
    selected = {case: (mode, left, right) for mode, case, left, right, _ in CASES}
    expectations = {("same_fraction", "eq"): True, ("same_fraction", "ne"): False,
                    ("invalid_leap_day", "eq"): False, ("invalid_offset", "eq"): False,
                    ("different_utf8", "lt"): True, ("prefix", "gt"): False}
    outcomes = {}
    for case, op in expectations:
        mode, left, right = selected[case]
        rows = {"left_value": (mode, case, left), "right_value": (mode, case, right), "comparison": (mode, case, op)}
        snapshots = {name: json.dumps([{"key": key}]).encode() for name, key in rows.items()}
        target = {"relation": "comparison", "key": encode_key(rows["comparison"])}
        proof = {"manifest_id": "m-1", "root": target, "witnesses": [{
            "rule_id": f"{mode}_{op}", "conclusion": target,
            "bindings": [{"variable": name, "value": value}
                         for name, value in (("?case", case), ("?left", left), ("?right", right))],
            "premises": [{"row": {"relation": name, "key": encode_key(rows[name])}, "polarity": "positive", "stratum": 0}
                         for name in ("left_value", "right_value")],
        }]}
        report = check(proof, manifest(snapshots), definitions, snapshots.__getitem__)
        outcomes[(case, op)] = report["valid"]
    assert outcomes == expectations
