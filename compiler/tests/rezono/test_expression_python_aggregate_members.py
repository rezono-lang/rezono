"""A native sum, min or max never lowers to an IR fold that drops an inapplicable member.

Authored from decisions/language-expression-semantics.md §1 (the `count`, `sum`, `min`, `max` row and the
paragraph after the table) and the settled decisions/conformance-value-agg-na-member.md: a sum of known 7 and
an inapplicable member is not applicable, and an integer fold may skip a member only when the lowering proves
the two results agree, including state and cause. A value column of a base relation holds a Value with a state
(contracts/rules.yaml, `Relation`), so nothing in the supplied signature proves that its members are known.
decisions/language-native-rules.md gives R044 for an aggregate measure that cannot be represented faithfully.
A ranged key column always carries a known value and stays the control.
"""

from copy import deepcopy

import pytest

from rezono_compiler import diagnostics, rules_dl
from rezono_compiler.native_rule_groups import lower_group_clause
from rezono_compiler.rules import with_strata


ORIGIN = {"file": "rezono/stock.rezono", "line": "4"}
PROGRAM = {"format": "rezono.rules/1", "pack": "stock"}

# `entry` keeps its integer `size` in the key and its integer `quantity` as a Value, which can be
# not_applicable (an optional slot) or unknown for one member of a group.
RELATIONS = [
    {"name": "shelf", "role": "base", "world": "closed", "key": [{"name": "zone", "type": "string"}]},
    {"name": "entry", "role": "base", "world": "closed",
     "key": [{"name": "zone", "type": "string"}, {"name": "item", "type": "string"},
             {"name": "size", "type": "integer"}],
     "values": [{"name": "quantity", "type": "integer"}]},
    {"name": "total", "role": "derived", "module": "stock", "explain": "materialize",
     "key": [{"name": "zone", "type": "string"}, {"name": "amount", "type": "integer"}]},
]


def clause(function, column):
    """rule total(a, t) when shelf(a) and t = entry(a, _, _).<function>(it.<column>)"""
    return {"rule": "total", "args": [{"path": ["a"]}, {"path": ["t"]}], "when": {"and": [
        {"call": ["shelf", [{"path": ["a"]}]]},
        {"cmp": ["=", {"path": ["t"]}, {"agg": [function, {"call": ["entry", [
            {"path": ["a"]}, {"wildcard": True}, {"wildcard": True}]]}, {"path": ["it", column]}]}]},
    ]}}


def lower(function, column):
    return lower_group_clause(clause(function, column), deepcopy(RELATIONS), module="stock", origin=dict(ORIGIN))


class InapplicableMemberSkipped(AssertionError):
    """The lowering emitted an IR fold over a Value column, which drops a not_applicable member."""


@pytest.mark.xfail(
    strict=True,
    raises=InapplicableMemberSkipped,
    reason="extra: Refuse a sum, min or max whose measure is a Value column (it can hold not_applicable or unknown) "
           "with R044 at the clause origin in _GroupClause.measure of compiler/rezono_compiler/native_rule_groups.py, "
           "and keep lowering a ranged key-column measure. Read decisions/language-expression-semantics.md §1 and "
           "decisions/conformance-value-agg-na-member.md. Waits for "
           "compiler/tests/rezono/test_expression_python_filtered_count.py::test_expression_python_filtered_count, "
           "which adds coded diagnostics to the same _GroupClause.refuse.",
)
def test_expression_python_aggregate_members():
    # Control: a ranged key column is always known, so the IR sum is the decided sum.
    [rule] = with_strata({**PROGRAM, "relations": deepcopy(RELATIONS), "rules": [lower("sum", "size")]})["rules"]
    assert rule["aggregates"] == [{"relation": "entry", "terms": ["?a", "_", "_"], "function": "sum",
                                   "as": "?t", "over": "size", "stratum": "0"}]

    for function in ("sum", "min", "max"):
        try:
            lowered = lower(function, "quantity")
        except (rules_dl.RuleError, diagnostics.Diagnosed) as error:
            found = list(getattr(error, "diagnostics", ()))
            assert [diagnostic.code for diagnostic in found] == ["R044"], str(error)
            span = found[0].span
            assert span is not None and span[:2] == (ORIGIN["file"], int(ORIGIN["line"])), span
            continue
        raise InapplicableMemberSkipped(f"{function} over the quantity Value lowered to {lowered['aggregates']}")
