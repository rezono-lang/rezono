"""A counter with an explicit bound (#351 P6.2): what the unrolled rule computes, and what happens at the bound.

The shape is a depth from seeds along steps, on the domain-free fixture pack. The batch backend is compared
with a plain fixpoint of the rules as written (always) and with Soufflé on the rule text as written (the
oracle, as a set; skipped without `souffle`). Where the count reaches its bound the two differ on purpose:
Soufflé stops there and keeps what it has, Rede raises. What is accepted and refused is in test_rules_dl.py."""

import shutil
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import souffle
from support import FIXTURE
from rede_compiler import batch, pack
from rede_compiler import rules as ir

SOUFFLE = pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
LAST = 2  # the counter is read while it is at most this: `n < 3`
TEXT = """
.decl step(a: symbol, b: symbol)
step(a, b) :- beta__alpha(a, b).

.decl depth(a: symbol, n: number)
depth(a, 0) :- alpha(a).
depth(a, 1) :- alpha__title(a, _).
depth(b, m) :- depth(a, n), n < 3, step(a, b), !alpha(b), m = n + 1.

.decl nearest(a: symbol, n: number)
nearest(a, n) :- depth(a, _), n = min d : { depth(a, d) }.
"""
NODE = st.sampled_from("abcdefg")
GRAPH = st.lists(st.tuples(NODE, NODE), max_size=12, unique=True)
SEEDS = st.lists(NODE, max_size=3, unique=True)


@pytest.fixture(scope="module")
def prog(tmp_path_factory):
    d = Path(shutil.copytree(FIXTURE, tmp_path_factory.mktemp("bound") / "pack"))
    (d / "rules").mkdir(exist_ok=True)
    (d / "rules" / "core.dl").write_text(TEXT)
    return ir.load(pack.read(d).rules)


def facts(seeds, late, steps):
    return {"alpha": [(a,) for a in seeds], "alpha__title": [(a, "t") for a in late], "beta__alpha": list(steps)}


def reference(seeds, late, steps):
    """The rules as written, to their fixpoint, and the rows the counting rule would add beyond its bound."""
    def moves(rows, reads):
        return {(b, n + 1) for a, n in rows if reads(n) for x, b in steps if x == a and b not in seeds}

    depth = {(a, 0) for a in seeds} | {(a, 1) for a in late}
    while not moves(depth, lambda n: n <= LAST) <= depth:
        depth |= moves(depth, lambda n: n <= LAST)
    return depth, moves(depth, lambda n: n > LAST)


def run(prog, data):
    con = batch.connect(prog, data)
    try:
        batch.compute(con, prog)
        return batch.read(con, prog)
    finally:
        con.close()


def text(rows):
    return {(a, str(n)) for a, n in rows}


@settings(deadline=None)
@given(seeds=SEEDS, late=SEEDS, steps=GRAPH)
def test_the_unrolled_counter_is_the_fixpoint_of_the_rules_or_an_error_at_the_bound(prog, seeds, late, steps):
    pytest.importorskip("duckdb")
    depth, beyond = reference(seeds, late, steps)
    if beyond:
        with pytest.raises(batch.BoundReached, match=rf"bound_reached: depth: rule depth_3 .*n <= {LAST}.* {len(beyond)} more"):
            run(prog, facts(seeds, late, steps))
        return
    got = run(prog, facts(seeds, late, steps))
    assert got["depth"] == text(depth)
    assert got["nearest"] == text({(a, min(n for x, n in depth if x == a)) for a, _ in depth})


def test_a_count_that_ends_at_the_bound_is_whole_and_one_that_goes_on_is_an_error(prog):
    pytest.importorskip("duckdb")
    chain = [("s", "a"), ("a", "b"), ("b", "c")]
    # the last row has depth 3, read by nothing: the bound is met, not passed
    assert run(prog, facts(["s"], [], chain))["depth"] == {("s", "0"), ("a", "1"), ("b", "2"), ("c", "3")}
    # one step more, a second start one step ahead, or a cycle: the count would go on
    for late, steps in ([], chain + [("c", "d")]), (["s"], chain), ([], [("s", "a"), ("a", "b"), ("b", "a")]):
        with pytest.raises(batch.BoundReached) as e:
            run(prog, facts(["s"], late, steps))
        assert e.value.code == "bound_reached"
    # the rows beyond the bound are the check view, which another engine reads as a red check
    con = batch.connect(prog, facts(["s"], [], chain + [("c", "d"), ("c", "e")]))
    with pytest.raises(batch.BoundReached, match="2 more"):
        batch.compute(con, prog)
    assert sorted(con.execute('SELECT * FROM "depth__exhausted"').fetchall()) == [("d", 4), ("e", 4)]


@SOUFFLE
@settings(deadline=None, max_examples=min(settings().max_examples, 100))
@given(seeds=SEEDS, late=SEEDS, steps=GRAPH)
def test_the_rules_as_written_equal_the_batch_backend_on_souffle_below_the_bound(prog, seeds, late, steps, tmp_path_factory):
    pytest.importorskip("duckdb")
    data = facts(seeds, late, steps)
    oracle = souffle.run(prog, data, tmp_path_factory.mktemp("s"), program_text=souffle.source(prog, [TEXT]))
    depth, beyond = reference(seeds, late, steps)
    assert oracle["depth"] == text(depth)   # Soufflé stops at the bound too, in silence
    if not beyond:
        assert run(prog, data) == oracle


def test_the_check_view_on_feldera_holds_the_rows_past_the_bound(prog):
    """RV-K18: on Feldera the engine SQL keeps the rows the counting rule would add past its bound in the
    materialized view `depth__exhausted`, which a reader takes as a red check (FELDERA_URL; the label `feldera`):
    two rows past the bound, and none once the count ends at it."""
    from feldera import URL, deploy, processed, push, query, stop

    from rede_compiler import rules_sql
    if not URL:
        pytest.skip("set FELDERA_URL to a running Feldera")
    name = "rede-rules-bound"
    deploy(name, rules_sql.feldera(prog), profile="unoptimized", workers=2)
    columns = {n: [c.name for c in r.key + r.values] for n, r in prog.relations.items() if r.role == "base"}

    def send(rows, op):
        processed(name, push(name, {rel: [{op: dict(zip(columns[rel], r))} for r in rs] for rel, rs in rows.items()}))

    def beyond():
        return {tuple(str(v) for v in r.values()) for r in query(name, 'SELECT * FROM "depth__exhausted"')}

    try:
        chain = [("s", "a"), ("a", "b"), ("b", "c")]
        send(facts(["s"], [], chain + [("c", "d"), ("c", "e")]), "insert")
        assert beyond() == {("d", "4"), ("e", "4")}
        send({"beta__alpha": [("c", "d"), ("c", "e")]}, "delete")
        assert beyond() == set()
    finally:
        stop(name)
