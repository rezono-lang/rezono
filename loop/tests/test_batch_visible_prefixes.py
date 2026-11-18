"""Check the relational batch selection against an independently enumerated oracle."""
from importlib.util import find_spec
from itertools import combinations

import pytest


def subsets(items, limit):
    return {
        frozenset(members)
        for width in range(min(len(items), limit) + 1)
        for members in combinations(items, width)
    }


def oracle(priorities, variant_valid, width, effects):
    candidates = subsets(priorities, width) - {frozenset()}
    eligible = {
        members for members in candidates
        if all(variant_valid(prefix) for prefix in subsets(members, len(members)))
        and all(not (effects[a]["write"] & effects[b]["write"]) for a, b in combinations(members, 2))
    }
    return eligible, min(eligible, key=lambda members: (-len(members), sorted(priorities[m] for m in members)))


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/safe-step-rounds.md. Use the width-bounded relational comparison in std-loop and expose "
        "it through loop.batch_selection.select_batch. The supplied prefix verdicts are independent, and the "
        "result must retain the certified batch domain and the chosen member identities. "
        "This test can start with hand-authored variants."
    ),
)
def test_batch_visible_prefixes():
    cases = [
        ({"protect": 1, "expose": 0}, lambda prefix: "expose" not in prefix or "protect" in prefix,
         2, frozenset({"protect"}), {}),
        ({"third": 30, "first": 10, "second": 20}, lambda prefix: len(prefix) <= 2,
         3, frozenset({"first", "second"}), {}),
        ({"write-left": 1, "write-right": 2}, lambda prefix: True,
         2, frozenset({"write-left", "write-right"}), {}),
        ({"left": 1, "right": 2}, lambda prefix: True, 2, frozenset({"left"}),
         {"left": "shared-slot", "right": "shared-slot"}),
    ]
    cases = [(priorities, valid, width, expected, {
        step: {"read": frozenset({"shared-context"}), "write": frozenset({overlap.get(step, step)})}
        for step in priorities
    }) for priorities, valid, width, expected, overlap in cases]
    for priorities, valid, width, expected, effects in cases:
        domain, chosen = oracle(priorities, valid, width, effects)
        assert chosen == expected
        if width == 3:
            assert {len(batch) for batch in domain} == {1, 2} and len(domain) == 6

    assert find_spec("loop.batch_selection") is not None, "The certified batch comparison is not wired"
    from loop.batch_selection import select_batch

    for priorities, valid, width, expected, effects in cases:
        domain, _ = oracle(priorities, valid, width, effects)
        prefixes = {members: valid(members) for members in subsets(priorities, width)}
        # The two independent writes may read the same preserved context.
        result = select_batch(priorities, prefixes, effects=effects, width=width)
        assert result["selected"] == expected and set(result["certified"]) == domain
        reversed_inputs = dict(reversed(list(priorities.items())))
        reversed_prefixes = dict(reversed(list(prefixes.items())))
        assert select_batch(reversed_inputs, reversed_prefixes, effects=effects, width=width) == result
