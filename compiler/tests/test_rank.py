"""The rank selector (rank.py, formal.md §3): proof depth, a fixed tie-break, the least fixpoint."""

from hypothesis import given
from hypothesis import strategies as st

from rezono_compiler import rank


def test_depth_not_steps():
    # c needs a and b, both of rank 1: rank 2, not 3.
    chosen = rank.choose([("a", [], ("r1",)), ("b", [], ("r1",)), ("c", ["a", "b"], ("r2",))])
    assert chosen == {"a": (1, 0), "b": (1, 1), "c": (2, 2)}


def test_least_rank_then_tie_break():
    chosen = rank.choose([("x", ["a"], ("r1",)), ("a", [], ("r0",)), ("x", [], ("r9",)), ("x", [], ("r5",))])
    assert chosen["x"] == (1, 3)


def test_a_cycle_alone_proves_nothing():
    assert rank.choose([("a", ["b"], ("r",)), ("b", ["a"], ("r",))]) == {}


def reference(instances):
    """The least rank of every conclusion by plain iteration to a fixpoint."""
    best, changed = {}, True
    while changed:
        changed = False
        for head, needs, _ in instances:
            if all(n in best for n in needs):
                r = 1 + max((best[n] for n in needs), default=0)
                if r < best.get(head, r + 1):
                    best[head], changed = r, True
    return best


NODES = st.sampled_from("abcde")
INSTANCES = st.lists(st.tuples(NODES, st.lists(NODES, max_size=3), st.tuples(st.integers(0, 3))), max_size=14)


@given(INSTANCES)
def test_least_fixpoint(instances):
    chosen = rank.choose(instances)
    assert {h: r for h, (r, _) in chosen.items()} == reference(instances)
    for head, (r, i) in chosen.items():
        h, needs, tie = instances[i]
        assert h == head and all(chosen[n][0] < r for n in needs)
        assert (r, tie, i) == min((1 + max((chosen[n][0] for n in ns), default=0), t, j)
                                  for j, (hh, ns, t) in enumerate(instances)
                                  if hh == head and all(n in chosen for n in ns))
