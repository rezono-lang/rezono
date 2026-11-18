"""`trace` (R8, R10): the proof graph as the relation `step`, and a walk over it as a rule program.

The walk runs on the batch backend and is compared with a plain breadth-first reference (always) and with
Soufflé on the program text as written (the oracle, as a set; skipped without `souffle`)."""

import shutil
from collections import defaultdict

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import souffle
from rezono_compiler import batch, explain, rules_dl, trace
from rezono_compiler import rules as ir
from rezono_compiler.explain import key_text

SOUFFLE = pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
ORACLE = settings(max_examples=min(settings().max_examples, 150))

RELATIONS = ["a", "b", "c"]
# Canonical keys, also with a quote, a backslash and a space, as real keys can have.
KEYS = [key_text([x]) for x in ["1", "2", "3", 'q"t', "b\\s", "x y"]] + [key_text(["1", "2"])]
NODE = st.tuples(st.sampled_from(RELATIONS), st.sampled_from(KEYS))
STEPS = st.lists(st.tuples(NODE, NODE, st.sampled_from(["positive", "negative", "contributes"]), st.integers(0, 2)),
                 max_size=40).map(lambda es: sorted({(*c, *p, how, pos) for c, p, how, pos in es}))
FILTER = st.none() | st.lists(st.sampled_from(RELATIONS), unique=True).map(sorted)


def reference(steps, start, direction, depth, keep, stop):
    """Breadth first, in plain Python: what the program must answer."""
    nxt = defaultdict(set)
    for c_r, c_k, p_r, p_k, _, _ in steps:
        a, b = ((c_r, c_k), (p_r, p_k)) if direction == "back" else ((p_r, p_k), (c_r, c_k))
        nxt[a].add(b)
    dist = {s: 0 for s in start}
    frontier, d = set(start), 0
    while frontier and (depth == "all" or d < depth):
        d += 1
        found = set()
        for n in frontier:
            if d > 1 and stop is not None and n[0] in stop:
                continue
            found |= {m for m in nxt[n] if m not in dist}
        dist.update({m: d for m in found})
        frontier = found
    shown = {n: d for n, d in dist.items() if d == 0 or keep is None or n[0] in keep}
    if depth == "all":
        return {n for n in shown}
    return {(*n, str(d)) for n, d in shown.items()}


@given(steps=STEPS, start=st.lists(NODE, min_size=1, max_size=3, unique=True),
       direction=st.sampled_from(trace.DIRECTIONS), depth=st.sampled_from([1, 2, 3, 5, "all"]),
       keep=FILTER, stop=FILTER)
def test_the_program_on_the_batch_backend_equals_breadth_first(steps, start, direction, depth, keep, stop):
    assert trace.run(steps, start, direction, depth, keep, stop) == reference(steps, start, direction, depth, keep, stop)


@SOUFFLE
@ORACLE
@given(steps=STEPS, start=st.lists(NODE, min_size=1, max_size=3, unique=True),
       direction=st.sampled_from(trace.DIRECTIONS), depth=st.sampled_from([1, 2, 4, "all"]),
       keep=FILTER, stop=FILTER)
def test_the_program_as_written_equals_the_batch_backend_on_souffle(steps, start, direction, depth, keep, stop,
                                                                    tmp_path_factory):
    text, doc = trace.compile_program(direction, depth, keep is not None, stop is not None)
    prog = ir.load(doc)
    data = {"step": steps, "start": start}
    if keep is not None:
        data["keep"] = [[r] for r in keep]
    if stop is not None:
        data["stop"] = [[r] for r in stop]
    # the oracle reads every derived relation back, so every one is an output there
    text = text.replace(".output node\n", "") + "".join(f".output {r}\n" for r in sorted(prog.derived()))
    got = souffle.run(prog, data, tmp_path_factory.mktemp("s"), program_text=text)["node"]
    assert got == trace.run(steps, start, direction, depth, keep, stop)


def test_bad_direction_and_depth_are_refused():
    for args in (("up", 1), ("back", 0), ("back", -1), ("back", True), ("forward", "some")):
        with pytest.raises(ValueError):
            trace.program(*args)


PROGRAM = """
.decl path(x: symbol, y: symbol)
path(x, y) :- e(x, y).
path(x, z) :- path(x, y), e(y, z).
.decl deg(x: symbol, n: number)
deg(x, n) :- v(x), n = count : { e(x, _) }.
.decl lone(x: symbol)
lone(x) :- v(x), !path(x, x).
"""


def chosen_graph():
    doc = rules_dl.read_program(PROGRAM, "test.dl", {"v": [("x", "string")], "e": [("x", "string"), ("y", "string")]},
                                "test")
    prog = ir.load(doc)
    con = batch.connect(prog, {"v": [["a"], ["b"], ["c"]], "e": [["a", "b"], ["b", "c"]]})
    batch.compute(con, prog)
    derived = batch.read(con, prog)
    rows = batch.read(con, prog, prog.base_used()) | derived
    witnesses = explain.Explainer(prog, rows, batch.witnesses(con, prog)).chosen()
    return trace.steps(prog, witnesses, rows)


def k(*parts):
    return key_text(parts)


def test_step_holds_premises_in_body_order_and_contributors_of_a_group():
    assert chosen_graph() == sorted([
        ("deg", k("a", "1"), "e", k("a", "b"), "contributes", 0),
        ("deg", k("a", "1"), "v", k("a"), "positive", 0),
        ("deg", k("b", "1"), "e", k("b", "c"), "contributes", 0),
        ("deg", k("b", "1"), "v", k("b"), "positive", 0),
        ("deg", k("c", "0"), "v", k("c"), "positive", 0),
        *[("lone", k(x), r, key, how, i) for x in "abc"
          for r, key, how, i in (("v", k(x), "positive", 0), ("path", k(x, x), "negative", 1))],
        ("path", k("a", "b"), "e", k("a", "b"), "positive", 0),
        ("path", k("a", "c"), "e", k("b", "c"), "positive", 1),
        ("path", k("a", "c"), "path", k("a", "b"), "positive", 0),
        ("path", k("b", "c"), "e", k("b", "c"), "positive", 0),
    ])


def test_premise_positions_come_from_the_rule_not_from_the_order_in_the_witness():
    doc = rules_dl.read_program(PROGRAM, "test.dl", {"v": [("x", "string")], "e": [("x", "string"), ("y", "string")]},
                                "test")
    prog = ir.load(doc)
    con = batch.connect(prog, {"v": [["a"], ["b"], ["c"]], "e": [["a", "b"], ["b", "c"]]})
    batch.compute(con, prog)
    rows = batch.read(con, prog, prog.base_used()) | batch.read(con, prog)
    witnesses = explain.Explainer(prog, rows, batch.witnesses(con, prog)).chosen()
    turned = [{**w, "premises": list(reversed(w.get("premises", [])))} for w in witnesses]
    assert trace.steps(prog, turned, rows) == trace.steps(prog, witnesses, rows) == chosen_graph()


def test_grounds_and_reach_on_a_chosen_graph():
    steps = chosen_graph()
    assert trace.run(steps, [("path", k("a", "c"))], "back", "all") == {
        ("path", k("a", "c")), ("path", k("a", "b")), ("e", k("a", "b")), ("e", k("b", "c"))}
    assert trace.run(steps, [("e", k("a", "b"))], "forward", 2) == {
        ("e", k("a", "b"), "0"), ("path", k("a", "b"), "1"), ("deg", k("a", "1"), "1"), ("path", k("a", "c"), "2")}
    # keep shows only some nodes; the walk still goes through the others
    assert trace.run(steps, [("path", k("a", "c"))], "back", "all", keep=["e"]) == {
        ("path", k("a", "c")), ("e", k("a", "b")), ("e", k("b", "c"))}
    # stop: reached, not gone past
    assert trace.run(steps, [("e", k("a", "b"))], "forward", 3, stop=["path"]) == {
        ("e", k("a", "b"), "0"), ("path", k("a", "b"), "1"), ("deg", k("a", "1"), "1")}


WEIGHED = """
.decl load(x: symbol, n: number)
load(x, n) :- v(x), n = sum z : { w(x, _, z) }.
.decl least(x: symbol, n: number)
least(x, n) :- v(x), n = min z : { w(x, _, z) }.
.decl deg(x: symbol, n: number)
deg(x, n) :- v(x), n = count : { w(x, _, _) }.
"""


def weighed():
    inputs = {"v": [("x", "string")], "w": [("x", "string"), ("y", "string"), ("w", "integer")]}
    prog = ir.load(rules_dl.read_program(WEIGHED, "test.dl", inputs, "test"))
    con = batch.connect(prog, {"v": [["a"], ["b"]], "w": [["a", "p", "3"], ["a", "q", "-4"], ["b", "p", "5"]]})
    batch.compute(con, prog)
    rows = batch.read(con, prog, prog.base_used()) | batch.read(con, prog)
    return prog, explain.Explainer(prog, rows, batch.witnesses(con, prog)).chosen(), rows


def test_a_contributes_edge_of_a_sum_or_a_min_carries_what_its_row_gives():
    """The value is the text the contributors hash states; a count edge and a premise carry none."""
    prog, witnesses, rows = weighed()
    valued = trace.steps(prog, witnesses, rows, valued=True)
    assert [s for s in valued if s[4] == "contributes"] == sorted([
        ("deg", k("a", "2"), "w", k("a", "p", "3"), "contributes", 0),
        ("deg", k("a", "2"), "w", k("a", "q", "-4"), "contributes", 0),
        ("deg", k("b", "1"), "w", k("b", "p", "5"), "contributes", 0),
        ("least", k("a", "-4"), "w", k("a", "p", "3"), "contributes", 0, "known:3"),
        ("least", k("a", "-4"), "w", k("a", "q", "-4"), "contributes", 0, "known:-4"),
        ("least", k("b", "5"), "w", k("b", "p", "5"), "contributes", 0, "known:5"),
        ("load", k("a", "-1"), "w", k("a", "p", "3"), "contributes", 0, "known:3"),
        ("load", k("a", "-1"), "w", k("a", "q", "-4"), "contributes", 0, "known:-4"),
        ("load", k("b", "5"), "w", k("b", "p", "5"), "contributes", 0, "known:5"),
    ])
    assert all(len(s) == 6 for s in valued if s[4] != "contributes")
    # The value is a function of the edge: without it, the relation `step` that `trace` walks.
    assert sorted({s[:6] for s in valued}) == trace.steps(prog, witnesses, rows)


def test_the_valued_edges_of_an_aggregate_are_its_contributors_and_hash_to_the_witness():
    """What the reader gets is what the hash proves: per aggregate, the sorted [key, value] of its edges
    (only [key] for a count) is the list `contributors_sha256` is taken over, and the sum is its result."""
    from rezono_canon import canonical_sha256

    prog, witnesses, rows = weighed()
    edges = defaultdict(list)
    for c_rel, c_key, _, p_key, how, position, *value in trace.steps(prog, witnesses, rows, valued=True):
        if how == "contributes":
            edges[c_rel, c_key, position].append([p_key, *value])
    seen = 0
    for w in witnesses:
        for a in w["aggregates"]:
            given = edges[w["conclusion"]["relation"], w["conclusion"]["key"], a["position"]]
            assert canonical_sha256(sorted(given)) == a["contributors_sha256"] and len(given) == a["count"]
            if w["rule_id"].startswith("load"):
                assert f"known:{sum(int(v.removeprefix('known:')) for _, v in given)}" == a["result"]
            seen += 1
    assert seen == 6


def test_a_cell_that_is_not_known_is_refused_not_stated_as_known():
    """A row given with None in the column a sum ranges over (a snapshot cell that is missing or not known)
    gives no contribution text: the valued graph is refused; without values the edges are as before."""
    prog, witnesses, rows = weighed()
    holed = rows | {"w": {r[:2] + (None,) if r[1] == "q" else r for r in rows["w"]}}
    with pytest.raises(explain.NoProof, match="not known"):
        trace.steps(prog, witnesses, holed, valued=True)
    assert len(trace.steps(prog, witnesses, holed)) == len(trace.steps(prog, witnesses, rows))
