"""Path bindings and their grounds on the ordinary native rule path.

Expectations come from decisions/language-expression-semantics.md §1, the rows "Literal, variable,
identifier", "Path", "Call", "Membership and range" and "Comparison": a typed head declares a type only, a
positive scalar equality binds its subject from the actual slot row, and a multivalued hop is matched
by its forward row. No membership or identifier premise is invented.
"""

import pytest

from rezono_compiler import pack
from expression_packs import author, compile_rules, literals, refusals, register, stage_pack


class PathBindingMismatch(AssertionError):
    """The ordinary compiler did not ground a path the way the expression contract requires."""


SOURCE = """rezono 0
pack minimal
rule ranked_zero(x: Stage) when x.rank = 0
rule follows(x: Stage, y: Stage) when y in x.next
rule stepped(x: Stage, y: Stage) when Stage.next(x, y)
rule listed_stage(x: Stage) when x in Stage
"""

# A typed head column that no premise binds: the declaration supplies a type, not a row.
UNBOUND = """rezono 0
pack minimal
rule floating(x: Stage, y: Stage) when x.rank = 0
"""


@pytest.mark.xfail(
    strict=True,
    raises=PathBindingMismatch,
    reason="Lower single-premise path and slot-call guards in compiler/rezono_compiler/native_rule_lowering.py: "
           "x.rank = 0 is the positive slot row stage__rank(?x, 0); y in x.next and Stage.next(x, y) are the "
           "forward row stage__next(?x, ?y); no membership premise is invented, and an unbound typed head "
           "column is R042. Read decisions/language-expression-semantics.md §1. "
           "Waits for test_expression_python_negated_call while it owns lower_source.",
)
def test_expression_python_path_bindings(tmp_path):
    directory = stage_pack(tmp_path)
    register(directory, author(directory, "paths", SOURCE))
    try:
        program = compile_rules(directory)
    except pack.CompileError as error:
        raise PathBindingMismatch(str(error)) from error
    rules = {rule["head"]["relation"]: rule for rule in program["rules"]}
    observed = {name: (rules[name]["head"]["terms"], literals(rules[name])) for name in
                ("ranked_zero", "follows", "stepped", "listed_stage") if name in rules}
    expected = {
        "ranked_zero": (["?x"], [("positive", "stage__rank", ["?x", "0"])]),
        "follows": (["?x", "?y"], [("positive", "stage__next", ["?x", "?y"])]),
        "stepped": (["?x", "?y"], [("positive", "stage__next", ["?x", "?y"])]),
        # Positive control: the membership form that already lowers.
        "listed_stage": (["?x"], [("positive", "stage", ["?x"])]),
    }
    if observed != expected:
        raise PathBindingMismatch(f"got {observed!r}, expected {expected!r}")
    for name in ("ranked_zero", "follows", "stepped"):
        assert not rules[name].get("aggregates") and not rules[name].get("conditions")

    unbound = stage_pack(tmp_path, "unbound")
    register(unbound, author(unbound, "floating", UNBOUND))
    found = refusals(unbound)
    if ("R042", "/decls/0/columns/1") not in found:
        raise PathBindingMismatch(f"an unbound typed head column gave {found!r}, expected R042 at /decls/0/columns/1")
