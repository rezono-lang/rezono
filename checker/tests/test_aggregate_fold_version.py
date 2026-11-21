"""The checker folds an aggregate by the format of its program: strict in invalid, unknown and not_applicable for
rezono.rules/2 (rezono 1), and as docs/formal.md section 6 gives for rezono.rules/1 (rezono 0)
(decisions/language-rezono-1-aggregate-spelling.md, section 2). Hand-written IR through load_rules and
check.recompute, the entry point of checker/tests/test_rule_ir.py and test_proof.py."""

import json

import pytest

from rezono_checker.check import recompute
from rezono_checker.rules import load_rules
from rezono_checker.snapshots import read_rows

FUNCTIONS = ("sum", "min", "max")


def program(fmt):
    """`<function>_amount(g, result)` folds the `amount` cells of every `cell(g, _)` row of one batch `g`."""
    return {
        "format": fmt, "pack": "sample",
        "relations": [
            {"name": "batch", "role": "base", "key": [{"name": "g", "type": "string"}]},
            {"name": "cell", "role": "base", "key": [{"name": "g", "type": "string"}, {"name": "row", "type": "string"}],
             "values": [{"name": "amount", "type": "integer"}]},
            *({"name": f"{function}_amount", "role": "derived",
               "key": [{"name": "g", "type": "string"}, {"name": "result", "type": "integer"}]} for function in FUNCTIONS),
        ],
        "rules": [
            {"id": f"{function}_amount", "stratum": "1",
             "head": {"relation": f"{function}_amount", "terms": ["?g", "?n"]},
             "body": [{"relation": "batch", "terms": ["?g"], "polarity": "positive", "stratum": "0"}],
             "aggregates": [{"relation": "cell", "terms": ["?g", "_"], "function": function, "over": "amount",
                             "as": "?n", "stratum": "0"}]}
            for function in FUNCTIONS
        ],
    }


SEVEN, FIVE = {"state": "known", "value": "7"}, {"state": "known", "value": "5"}
CELLS = {
    "known": [SEVEN, FIVE],
    "with_na": [SEVEN, {"state": "not_applicable"}],
    "with_unknown": [SEVEN, {"state": "unknown"}],
    "with_invalid": [SEVEN, {"state": "invalid"}],
    "only_na": [{"state": "not_applicable"}],
}
ROWS = read_rows(json.dumps([{"key": [g, f"r{i}"], "values": {"amount": cell}}
                             for g, cells in CELLS.items() for i, cell in enumerate(cells)]).encode(), "json")
CONTROL = {"sum": "known:12", "min": "known:5", "max": "known:7"}  # every cell known: both formats agree


def folded(rules):
    """Per batch and function, the result `recompute` gives the aggregate."""
    return {g: {function: recompute(rules[f"{function}_amount"].aggregates[0], [(0, g)], ROWS)[2]
                for function in FUNCTIONS} for g in CELLS}


def state(result):
    return result.partition(":")[0]


class MissingFourStateFold(AssertionError):
    """The checker did not load a rezono.rules/2 program, or did not fold its aggregates strictly in all four states."""


def test_rules_2_aggregates_fold_four_states():
    try:
        rules = load_rules(program("rezono.rules/2"))
    except ValueError as error:
        raise MissingFourStateFold(f"load_rules refused the rezono.rules/2 program: {error}") from None
    got = folded(rules)
    want = {
        "known": CONTROL,
        "with_na": dict.fromkeys(FUNCTIONS, "not_applicable"),
        "with_unknown": dict.fromkeys(FUNCTIONS, "unknown"),
        "with_invalid": dict.fromkeys(FUNCTIONS, "invalid"),
        "only_na": dict.fromkeys(FUNCTIONS, "not_applicable"),
    }
    # A result in a state may carry its reason after the state; a known result is compared whole.
    seen = {g: {f: (r if g == "known" else state(r)) for f, r in results.items()} for g, results in got.items()}
    if seen != want:
        raise MissingFourStateFold(json.dumps({"got": got, "want": want}, indent=2))


def test_rules_1_aggregates_keep_formal_6():
    """Counter-case: in rezono.rules/1 invalid blocks, unknown is strict and not_applicable does not count."""
    assert folded(load_rules(program("rezono.rules/1"))) == {
        "known": CONTROL,
        "with_na": {"sum": "known:7", "min": "known:7", "max": "known:7"},
        "with_unknown": dict.fromkeys(FUNCTIONS, "unknown"),
        "with_invalid": dict.fromkeys(FUNCTIONS, "invalid"),
        "only_na": {"sum": "known:0", "min": "not_applicable", "max": "not_applicable"},
    }
