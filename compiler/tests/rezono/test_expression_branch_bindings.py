"""Conjunction, disjunction and computed bindings on the ordinary native rule path.

Expectations come from decisions/language-expression-semantics.md §1, the rows "a and b", "a or b",
"not p" and "Arithmetic and result assignment": a conjunction exports compatible bindings in order,
a disjunction exports only names every branch binds, a computed result feeds the head, and a
negative key needs a positive binding (R042).
"""

import pytest

from rezono_compiler import pack
from expression_packs import author, compile_rules, literals, refusals, register, stage_pack


class BranchBindingMismatch(AssertionError):
    """The ordinary compiler bound or refused a name differently from the expression contract."""


SOURCE = """rezono 0
pack minimal
rule linked(x: Stage) when x in Stage and (x.rank = 0 or y in x.next)
rule bumped(x: Stage, n: Int) when x in Stage and x.rank = k and n = k + 1
"""

# `y` is bound by one alternative only, so the head cannot read it.
BRANCH_LOCAL = """rezono 0
pack minimal
rule leaky(x: Stage, y: Stage) when x in Stage and (y in x.next or x.rank = 0)
"""

# The negative key `y` has no positive binding.
UNSAFE_NEGATION = """rezono 0
pack minimal
rule unsafe(x: Stage) when x in Stage and not Stage.next(x, y)
"""


@pytest.mark.xfail(
    strict=True,
    raises=BranchBindingMismatch,
    reason="M3: Lower conjunctions, disjunctions and assignments in compiler/rezono_compiler/native_rule_lowering.py: "
           "one rule per alternative, a computed n = k + 1 as an IR assignment, and R042 for a branch-local head "
           "name and for an unbound negative key. Read decisions/language-expression-semantics.md §1.",
)
def test_expression_python_branch_bindings(tmp_path):
    directory = stage_pack(tmp_path)
    register(directory, author(directory, "branches", SOURCE))
    try:
        program = compile_rules(directory)
    except pack.CompileError as error:
        raise BranchBindingMismatch(str(error)) from error
    clauses = {}
    for rule in program["rules"]:
        clauses.setdefault(rule["head"]["relation"], []).append(rule)
    linked = sorted(literals(rule) for rule in clauses.get("linked", []))
    expected_linked = sorted([
        [("positive", "stage", ["?x"]), ("positive", "stage__rank", ["?x", "0"])],
        [("positive", "stage", ["?x"]), ("positive", "stage__next", ["?x", "?y"])],
    ])
    if linked != expected_linked or any(rule["head"]["terms"] != ["?x"] for rule in clauses["linked"]):
        raise BranchBindingMismatch(f"linked lowered to {linked!r}, expected one clause per alternative")
    [bumped] = clauses.get("bumped", [None])
    if bumped is None or (bumped["head"]["terms"], literals(bumped), bumped.get("assignments")) != (
        ["?x", "?n"],
        [("positive", "stage", ["?x"]), ("positive", "stage__rank", ["?x", "?k"])],
        [{"var": "?n", "op": "add", "left": "?k", "right": "1"}],
    ):
        raise BranchBindingMismatch(f"bumped lowered to {bumped!r}")

    for name, source, pointer in (
        ("local", BRANCH_LOCAL, "/decls/0/columns/1"),
        ("negative", UNSAFE_NEGATION, "/decls/0/when/and/1/not/call/1/1"),
    ):
        refused = stage_pack(tmp_path, name)
        register(refused, author(refused, name, source))
        found = refusals(refused)
        if ("R042", pointer) not in found:
            raise BranchBindingMismatch(f"{name}: got {found!r}, expected R042 at {pointer}")
