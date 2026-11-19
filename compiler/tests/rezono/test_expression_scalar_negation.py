"""Scalar negation on the ordinary native rule path keeps an undecided value undecided.

Expectations come from decisions/language-expression-semantics.md §1, the rows "not p" and
"Comparison", and §2 rule 1: a true conclusion from `not (x.rank = 0)` needs a readable known value
that differs from zero. A stage without a rank row derives nothing, unlike an anti-join against the
success rows of `x.rank = 0`, which would derive it.
"""

import json

import pytest

from rezono_compiler import batch, pack, rules
from expression_packs import author, compile_rules, register, stage_pack


class ScalarNegationMismatch(AssertionError):
    """The ordinary compiler did not lower scalar negation as a positive row with a comparison."""


SOURCE = """rezono 0
pack minimal
rule nonzero(x: Stage) when x in Stage and not (x.rank = 0)
"""

ROWS = {
    "stage": [("a",), ("b",), ("c",)],
    "stage__rank": [("b", 0), ("c", 2)],
}


@pytest.mark.xfail(
    strict=True,
    raises=ScalarNegationMismatch,
    reason="M3: Lower not (x.rank = 0) in compiler/rezono_compiler/native_rule_lowering.py as the positive slot row "
           "stage__rank(?x, ?v) with the condition ne(?v, 0), never as an anti-join. Read "
           "decisions/language-expression-semantics.md §1 and §2 rule 1. Waits for "
           "test_expression_python_branch_bindings, which lowers the conjunction and path premises it uses.",
)
def test_expression_python_scalar_negation(tmp_path):
    directory = stage_pack(tmp_path)
    register(directory, author(directory, "negation", SOURCE))
    try:
        program = compile_rules(directory)
    except pack.CompileError as error:
        raise ScalarNegationMismatch(str(error)) from error
    [rule] = [rule for rule in program["rules"] if rule["head"]["relation"] == "nonzero"]
    body = [(item["polarity"], item["relation"], item["terms"]) for item in rule["body"]]
    rank = [terms for polarity, relation, terms in body if relation == "stage__rank"]
    if (len(body) != 2 or ("positive", "stage", ["?x"]) not in body or len(rank) != 1
            or rank[0][0] != "?x" or not rank[0][1].startswith("?") or rank[0][1] == "?x"):
        raise ScalarNegationMismatch(f"nonzero lowered to {body!r}")
    value = rank[0][1]
    conditions = rule.get("conditions", [])
    if conditions != [{"op": "ne", "left": value, "right": "0"}] or rule.get("aggregates"):
        raise ScalarNegationMismatch(f"nonzero compares with {conditions!r}")

    # Independent evaluation of the lowered program: only the readable known nonzero rank concludes.
    prog = rules.load(program)
    with batch.connect(prog, ROWS) as con:
        batch.compute(con, prog)
        derived = batch.read(con, prog)
    assert sorted(derived["nonzero"]) == [("c",)]
