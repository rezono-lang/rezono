"""Theory std-order: its axioms and rules against independent oracles.

Three evaluations must agree as sets: an exact Python reference written from the definitions, the DuckDB
batch backend on the compiled IR, and Soufflé on rules/order.dl as written (when present, as in CI). The
must-fail cases show that each axiom fires: a cycle, a self-loop and a conflicting rank give invariant rows.
No domain: the elements are plain letters.
"""

import shutil
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from rezono_compiler import emit, pack
from rezono_compiler import rules as ir

THEORY = Path(__file__).resolve().parents[2] / "packs" / "std-order"
pytest.importorskip("duckdb")


def reference(precedes, rank):
    """Compute the order relations by fixpoint: before is the transitive closure of precedes; comparable
    is before in either direction; order_cycle is what comes before itself; rank_conflict is a pair in
    that closure whose ranks do not increase (if a comes before b and both have a rank)."""
    before = set(precedes)
    while True:
        more = {(a, d) for a, b in before for c, d in precedes if b == c} - before
        if not more:
            break
        before |= more
    ranks = {}
    for e, n in rank:
        ranks.setdefault(e, set()).add(n)
    return {
        "before": before,
        "comparable": before | {(b, a) for a, b in before},
        "order_cycle": {(a,) for a, b in before if a == b},
        "rank_conflict": {(a, b) for a, b in before for x in ranks.get(a, ()) for y in ranks.get(b, ()) if x >= y},
    }


def program():
    return ir.load(pack.read(THEORY).rules)


def batch_eval(prog, precedes, rank):
    from rezono_compiler import batch
    con = batch.connect(prog, {"ordered__precedes": sorted(precedes), "ordered__rank": sorted(rank)})
    batch.compute(con, prog)
    return batch.read(con, prog)


def as_text(result):
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in result.items()}


def evaluate(precedes, rank, tmp_path):
    """Every engine at hand, each compared with the reference."""
    prog = program()
    want = as_text(reference(set(precedes), set(rank)))
    assert as_text(batch_eval(prog, precedes, rank)) == want
    if shutil.which("souffle"):
        import souffle
        text = souffle.source(prog, [p.read_text("utf-8") for p in sorted((THEORY / "rules").glob("*.dl"))])
        data = {"ordered__precedes": sorted(precedes), "ordered__rank": sorted(rank)}
        assert souffle.run(prog, data, tmp_path, program_text=text) == want
    return want


def test_the_theory_is_fact_free_and_compiles_on_its_own():
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True and not (THEORY / "facts").exists()
    assert {"ordered", "scale"} <= set(theory.kinds)
    files = emit.compile_pack(theory)
    assert '"ordered__precedes"' in files["engine/tables.sql"] and '"ordered__rank"' in files["engine/tables.sql"]
    prog = program()
    assert sorted(r.name for r in prog.relations.values() if r.role == "derived") == [
        "before", "comparable", "order_cycle", "rank_conflict"]
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "invariant", False)) == ["order_cycle", "rank_conflict"]
    assert [q["term"] for q in theory.questions] == ["order_grounds", "order_reach"]


def test_a_chain_is_totally_ordered_and_consistent(tmp_path):
    got = evaluate([("a", "b"), ("b", "c"), ("c", "d")], [("a", 1), ("b", 2), ("d", 9)], tmp_path)
    assert got["before"] == {("a", "b"), ("a", "c"), ("a", "d"), ("b", "c"), ("b", "d"), ("c", "d")}
    assert len(got["comparable"]) == 12
    assert got["order_cycle"] == set() and got["rank_conflict"] == set()   # c has no rank: no conflict


def test_incomparable_elements_stay_incomparable(tmp_path):
    # A diamond and a separate pair: b and c are incomparable, and so is anything across the two parts.
    got = evaluate([("a", "b"), ("a", "c"), ("b", "d"), ("c", "d"), ("x", "y")], [], tmp_path)
    assert ("b", "c") not in got["comparable"] and ("c", "b") not in got["comparable"]
    assert ("a", "x") not in got["comparable"] and ("a", "d") in got["before"]
    assert got["order_cycle"] == set()


def test_must_fail_a_cycle_breaks_the_strict_partial_order(tmp_path):
    got = evaluate([("a", "b"), ("b", "c"), ("c", "a"), ("c", "d")], [], tmp_path)
    assert got["order_cycle"] == {("a",), ("b",), ("c",)}   # d lies after the cycle, not on it


def test_must_fail_a_self_loop_breaks_irreflexivity(tmp_path):
    assert evaluate([("a", "a")], [], tmp_path)["order_cycle"] == {("a",)}


def test_must_fail_a_rank_that_does_not_increase(tmp_path):
    got = evaluate([("a", "b"), ("b", "c")], [("a", 5), ("b", 5), ("c", 2)], tmp_path)
    # Equal is a conflict too (strictly increasing), and the closure pair (a, c) conflicts as well.
    assert got["rank_conflict"] == {("a", "b"), ("b", "c"), ("a", "c")}
    assert got["order_cycle"] == set()


def test_must_fail_a_conflict_across_an_unranked_middle(tmp_path):
    """a -> b -> c, rank(a) = 9, no rank for b, rank(c) = 2: no direct step has two ranks, yet a comes
    before c with a lower rank after it. The invariant reads the closure, so the conflict shows."""
    got = evaluate([("a", "b"), ("b", "c")], [("a", 9), ("c", 2)], tmp_path)
    assert got["rank_conflict"] == {("a", "c")}
    # A missing rank at an end stays allowed: without rank(c) there is no conflict.
    assert evaluate([("a", "b"), ("b", "c")], [("a", 9)], tmp_path)["rank_conflict"] == set()


def test_reversed_arrows_are_a_failing_control():
    """The comparison is sensitive to direction: the reference on reversed arrows differs."""
    chain = {("a", "b"), ("b", "c")}
    assert as_text(batch_eval(program(), chain, set()))["before"] != as_text(
        reference({(b, a) for a, b in chain}, set()))["before"]


NODES = st.sampled_from("abcdef")


@settings(max_examples=60)
@given(precedes=st.sets(st.tuples(NODES, NODES), max_size=12),
       rank=st.sets(st.tuples(NODES, st.integers(-3, 3)), max_size=8))
def test_axioms_and_rules_agree_with_the_reference_on_any_graph(precedes, rank, tmp_path_factory):
    """Property (Hypothesis): on any finite graph and ranks, every engine equals the reference; a graph
    without a cycle never has order_cycle rows, and ranks taken from a topological order never conflict."""
    got = evaluate(sorted(precedes), sorted(rank), tmp_path_factory.mktemp("order"))
    acyclic = not got["order_cycle"]
    if acyclic:
        assert all((b, a) not in got["before"] for a, b in got["before"])   # antisymmetric, so strict
        depth = {e: sum(1 for x, y in got["before"] if y == e) for e in "abcdef"}
        assert as_text(reference(set(precedes), {(e, d) for e, d in depth.items()}))["rank_conflict"] == set()


def test_a_domain_kind_that_is_ordered_gets_the_theory_through_the_ordinary_compiler(tmp_path):
    """The binding that runs today, without view lowering (lane G, G04): a domain pins the theory, and a kind
    of its own is Ordered (is_a). Its elements are in the theory's tables, so the rules and axioms hold for
    them through the ordinary compiler. A view with other names waits for the lowering."""
    import yaml
    from rezono_compiler import batch, modules, scenarios

    domain = tmp_path / "bound"
    for folder in ("schema", "labels", "facts"):
        (domain / folder).mkdir(parents=True)
    (domain / "pack.yaml").write_text(yaml.safe_dump({
        "name": "bound", "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-order", "path": str(THEORY), "sha256": modules.pack_hash(THEORY)}]}), "utf-8")
    (domain / "schema" / "bound.yaml").write_text(yaml.safe_dump({
        "id": "https://rezono.example/bound", "name": "bound", "prefixes": {"linkml": "https://w3id.org/linkml/"},
        "imports": ["linkml:types", "std-order:order"], "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Step": {"is_a": "Ordered", "attributes": {"title": {}}}}}), "utf-8")
    (domain / "labels" / "en.yaml").write_text("step: step\nstep.title: title\n", "utf-8")
    (domain / "channels.yaml").write_text("kinds:\n  - {kind: step, shape: rect}\n", "utf-8")
    (domain / "facts" / "all.yaml").write_text(yaml.safe_dump({
        "scale": [{"id": "route"}],
        "step": [{"id": "a", "title": "A", "on_scale": "route", "rank": 1, "precedes": ["b"]},
                 {"id": "b", "title": "B", "on_scale": "route", "precedes": ["c"]},
                 {"id": "c", "title": "C", "on_scale": "route", "rank": 1}]}), "utf-8")
    model = pack.read(domain)
    assert model.kinds["step"].parent == "ordered" and model.meta["theory"] is False
    prog = ir.load(model.rules)
    (_, rows), = scenarios.states(model, domain)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    got = as_text(batch.read(con, prog))
    assert got["before"] == {("a", "b"), ("b", "c"), ("a", "c")}
    assert got["rank_conflict"] == {("a", "c")} and got["order_cycle"] == set()   # the axiom reads the domain's rows
