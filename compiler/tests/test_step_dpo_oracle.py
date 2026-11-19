"""Compare grounded step matches and row deltas with the isolated DPO oracle."""

import os
import subprocess
from importlib.util import find_spec
from pathlib import Path

import pytest


PROJECT = Path(__file__).parent / "catlab/dpo"

# Each graph has keyed items and keyed arrows. The four columns are X, L, K and R.
# A guard supplies a larger graph that must not extend the same match of L.
CASES = {
    "create": ("a|", "|", "|", "b|", ("b|",)),
    "duplicate_create": ("a,b|", "|", "|", "b|", ("b|",)),
    "dangling": ("a,b,c|edge:a:b", "b|", "|", "|", ()),
    "remove_incidence": ("a,b,c|edge:a:b", "a,b|edge:a:b", "a|", "a|", ()),
    "move": ("a,b,c|edge:a:b", "a,b,c|edge:a:b", "a,b,c|", "a,b,c|edge:c:b", ()),
    "alias": ("a|", "?first,?second|", "?first,?second|", "?first,?second|", ()),
    "all_isolated_matches": ("a,b,c,d|edge:a:b", "?item|", "|", "|", ()),
    "guard_clear": ("a,b|", "a,b|", "a,b|", "a,b|work:a:b", ("a,b|guard1:a:b", "a,b|guard2:a:b")),
    "guard_one": ("a,b|guard1:a:b", "a,b|", "a,b|", "a,b|work:a:b", ("a,b|guard1:a:b", "a,b|guard2:a:b")),
    "guard_two": ("a,b|guard1:a:b,guard2:a:b", "a,b|", "a,b|", "a,b|work:a:b",
                  ("a,b|guard1:a:b", "a,b|guard2:a:b")),
    "guard_created": ("a,b|work:a:b", "a,b|", "a,b|", "a,b|guard1:a:b", ("a,b|work:a:b",)),
    "preceding_delete": ("a,c|", "a,b|", "a,b|", "a,b|work:a:b", ()),
    "independent_ab": ("a,b|", "|", "|", "c|", ()),
    "independent_ba": ("a,c|", "|", "|", "b|", ()),
    "third_reservation": ("a,b|one:a:b,two:a:b", "a,b|", "a,b|", "a,b|three:a:b", ()),
}


def keyed_graph(text):
    vertices, edges = text.split("|")
    links = [tuple(edge.split(":")) for edge in edges.split(",") if edge]
    return {
        "item": [(item,) for item in vertices.split(",") if item],
        "link": [(key,) for key, _, _ in links],
        "link__tail": [(key, tail) for key, tail, _ in links],
        "link__head": [(key, head) for key, _, head in links],
    }


def normalized(match):
    typed_fields = ("matched", "removed", "added", "preserved")
    return result(*([":".join((relation, *row)) for relation, row in match[field]] for field in typed_fields))


def result(matched, removed, added, preserved):
    return tuple(tuple(sorted(field)) for field in (matched, removed, added, preserved))


ITEMS = ("item:a", "item:b", "item:c")
EDGE = ("link:edge", "link__head:edge:b", "link__tail:edge:a")
WORK = ("link:work", "link__head:work:b", "link__tail:work:a")
EXPECTED = {
    "create": {result((), (), ("item:b",), ("item:a",))},
    "duplicate_create": set(),
    "dangling": set(),
    "remove_incidence": {result((*ITEMS[:2], *EDGE), ("item:b", *EDGE), (), ("item:a", "item:c"))},
    "move": {result((*ITEMS, *EDGE), ("link__tail:edge:a",), ("link__tail:edge:c",),
                    (*ITEMS, "link:edge", "link__head:edge:b"))},
    "alias": set(),
    "all_isolated_matches": {
        result(("item:c",), ("item:c",), (), ("item:a", "item:b", "item:d", *EDGE)),
        result(("item:d",), ("item:d",), (), (*ITEMS, *EDGE)),
    },
    "guard_clear": {result(ITEMS[:2], (), WORK, ITEMS[:2])},
    "guard_one": set(),
    "guard_two": set(),
    "guard_created": set(),
    "preceding_delete": set(),
    "independent_ab": {result((), (), ("item:c",), ITEMS[:2])},
    "independent_ba": {result((), (), ("item:b",), ("item:a", "item:c"))},
    "third_reservation": {result(ITEMS[:2], (), ("link:three", "link__head:three:b", "link__tail:three:a"),
                                 (*ITEMS[:2], "link:one", "link:two", "link__head:one:b", "link__head:two:b",
                                  "link__tail:one:a", "link__tail:two:a"))},
}


def oracle(julia):
    executable = [julia, "--startup-file=no", f"--project={PROJECT}"]
    cases = "\n".join("\t".join((name, base, left, keep, right, ";".join(guards)))
                      for name, (base, left, keep, right, guards) in CASES.items())
    output = subprocess.run([*executable, str(PROJECT / "step_matches.jl")], input=cases, encoding="utf-8",
                            capture_output=True, timeout=360)
    if output.returncode:
        pytest.fail(output.stderr)
    compared = {name: set() for name in CASES}
    for line in output.stdout.splitlines():
        name, *columns = line.split("\t")
        if len(columns) != 4 or name not in compared:
            pytest.fail(f"Unexpected Julia oracle output {line!r}")
        compared[name].add(result(*(field.split(",") if field else [] for field in columns)))
    if compared != EXPECTED:
        pytest.fail(f"The pinned Julia oracle disagrees with the authored match and delta sets: {compared!r}")
    return compared


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="extra: Compare the typed step matcher in compiler/rezono_compiler/step_dpo.py with the pinned "
                          "AlgebraicRewriting oracle. Read decisions/safe-step-rounds.md. "
                          "Waits for compiler/tests/test_step_variant_rows.py::test_step_variant_rows.")
def test_step_dpo_oracle():
    julia = os.environ.get("REZONO_DPO_JULIA")
    expected = oracle(julia) if julia else EXPECTED
    assert find_spec("rezono_compiler.step_dpo"), "the compiler has no typed step matcher to compare"
    from rezono_compiler.step_dpo import match_effects

    actual_rows = {}
    for name, (base, left, keep, right, guards) in CASES.items():
        actual = match_effects(*(keyed_graph(graph) for graph in (base, left, keep, right)),
                               tuple(keyed_graph(guard) for guard in guards), complete=True)
        actual_rows[name] = {normalized(match) for match in actual["matches"]}
        assert actual_rows[name] == expected[name], name

    def after(name):
        [(_, _, added, preserved)] = actual_rows[name]
        return set(added) | set(preserved)

    assert after("independent_ab") == after("independent_ba") == set(ITEMS)
    # A structurally allowed third reservation can still violate a declared capacity of two.
    assert sum(row.startswith("link:") for row in after("third_reservation")) == 3

    base, left, keep, right, guards = CASES["guard_clear"]
    no_coverage = match_effects(*(keyed_graph(graph) for graph in (base, left, keep, right)),
                                tuple(keyed_graph(guard) for guard in guards), complete=False)
    assert no_coverage["state"] == "unknown" and not no_coverage["matches"]
