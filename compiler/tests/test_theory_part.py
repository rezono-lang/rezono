"""Theory std-part (#314 §5.2, T3; lane G, G06): its axioms and rules against independent oracles.

Three evaluations must agree as sets: an exact Python reference written from the definitions (walking up
from each part, not a join), the DuckDB batch backend on the compiled IR, and Soufflé on rules/part.dl as
written (when present, as in CI). The must-fail cases show that each axiom fires: the cycle as an invariant
row, a second whole and a repeat below one as checks of the schema. No domain: the elements are letters.
"""

import json
import shutil
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from rede_compiler import emit, pack
from rede_compiler import rules as ir

THEORY = Path(__file__).resolve().parents[2] / "packs" / "std-part"
pytest.importorskip("duckdb")
DERIVED = ["has_whole", "outermost", "part_cycle", "within"]


def reference(part_of):
    """The definitions of the README: x is within every whole reached by walking up part_of; the outermost
    whole is one reached that is part of nothing; a part cycle is an element reached from itself."""
    up = {}
    for x, w in part_of:
        up.setdefault(x, set()).add(w)
    within = set()
    for x in up:
        seen, todo = set(), list(up[x])
        while todo:
            w = todo.pop()
            if w not in seen:
                seen.add(w)
                todo.extend(up.get(w, ()))
        within |= {(x, w) for w in seen}
    return {
        "within": within,
        "has_whole": {(x,) for x in up},
        "outermost": {(x, w) for x, w in within if w not in up},
        "part_cycle": {(x,) for x, w in within if x == w},
    }


def program():
    return ir.load(pack.read(THEORY).rules)


def batch_eval(prog, data):
    from rede_compiler import batch
    con = batch.connect(prog, data)
    batch.compute(con, prog)
    return batch.read(con, prog)


def as_text(result):
    return {name: {tuple(str(v) for v in row) for row in rows} for name, rows in result.items()}


def evaluate(part_of, tmp_path):
    """Every engine at hand, each compared with the reference."""
    prog, data = program(), {"constituent__part_of": sorted(part_of)}
    want = as_text(reference(set(part_of)))
    assert as_text(batch_eval(prog, data)) == want
    if shutil.which("souffle"):
        import souffle
        text = souffle.source(prog, [p.read_text("utf-8") for p in sorted((THEORY / "rules").glob("*.dl"))])
        assert souffle.run(prog, data, tmp_path, program_text=text) == want
    return want


def test_the_theory_is_fact_free_and_compiles_on_its_own():
    theory = pack.read(THEORY)
    assert theory.meta["theory"] is True and not (THEORY / "facts").exists()
    assert set(theory.kinds) == {"constituent"}
    files = emit.compile_pack(theory)
    assert '"constituent__part_of"' in files["engine/tables.sql"] and '"constituent__repeat"' in files["engine/tables.sql"]
    prog = program()
    assert sorted(r.name for r in prog.relations.values() if r.role == "derived") == DERIVED
    assert sorted(r.name for r in prog.relations.values() if getattr(r, "invariant", False)) == ["part_cycle"]
    assert [q["term"] for q in theory.questions] == ["part_grounds", "part_reach"]


def test_two_axioms_are_checks_of_the_schema():
    """At most one direct whole, and a repeat of at least 1: the compiler makes each a blocking check."""
    theory = pack.read(THEORY)
    bundle = json.loads(emit.compile_pack(theory)["bundle/schema-bundle.json"])
    checks = {c["view"]: c["relation"] for c in bundle["checks"]}
    assert checks["constituent__part_of__functionality"] == "rede__functionality"
    assert checks["constituent__repeat__value_range"] == "rede__value_range"
    slots = theory.kinds["constituent"].slots
    assert not slots["part_of"].multivalued and int(slots["repeat"].minimum) == 1


def test_a_forest_gives_each_part_its_wholes_and_one_outermost(tmp_path):
    # Two trees: a > b > c, a > d, and x > y.
    got = evaluate([("b", "a"), ("c", "b"), ("d", "a"), ("y", "x")], tmp_path)
    assert got["within"] == {("b", "a"), ("c", "b"), ("c", "a"), ("d", "a"), ("y", "x")}
    assert got["outermost"] == {("b", "a"), ("c", "a"), ("d", "a"), ("y", "x")}
    assert got["has_whole"] == {("b",), ("c",), ("d",), ("y",)} and got["part_cycle"] == set()


def test_must_fail_a_cycle_breaks_the_forest(tmp_path):
    got = evaluate([("a", "b"), ("b", "c"), ("c", "a"), ("d", "a")], tmp_path)
    assert got["part_cycle"] == {("a",), ("b",), ("c",)}      # d hangs below the cycle, not on it
    assert got["outermost"] == set()                           # nothing on or below a cycle has an outermost whole


def test_must_fail_a_part_of_itself(tmp_path):
    assert evaluate([("a", "a")], tmp_path)["part_cycle"] == {("a",)}


def test_reversed_arrows_are_a_failing_control():
    """The comparison is sensitive to direction: the reference on reversed arrows differs."""
    tree = {("b", "a"), ("c", "b")}
    got = as_text(batch_eval(program(), {"constituent__part_of": sorted(tree)}))
    assert got["outermost"] != as_text(reference({(w, x) for x, w in tree}))["outermost"]


def bound(tmp_path, constituents):
    """A domain that pins the theory and whose kind Piece is a Constituent (is_a), with these rows."""
    import yaml
    from rede_compiler import modules

    domain = tmp_path / "bound"
    for folder in ("schema", "labels", "facts"):
        (domain / folder).mkdir(parents=True)
    (domain / "pack.yaml").write_text(yaml.safe_dump({
        "name": "bound", "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-part", "path": str(THEORY), "sha256": modules.pack_hash(THEORY)}]}), "utf-8")
    (domain / "schema" / "bound.yaml").write_text(yaml.safe_dump({
        "id": "https://rede.example/bound", "name": "bound", "prefixes": {"linkml": "https://w3id.org/linkml/"},
        "imports": ["linkml:types", "std-part:part"], "default_range": "string", "annotations": {"layer": "facts"},
        "classes": {"Piece": {"is_a": "Constituent", "attributes": {"title": {}}}}}), "utf-8")
    (domain / "labels" / "en.yaml").write_text("piece: piece\npiece.title: title\n", "utf-8")
    (domain / "channels.yaml").write_text("kinds:\n  - {kind: piece, shape: rect}\n", "utf-8")
    (domain / "facts" / "all.yaml").write_text(yaml.safe_dump({"piece": constituents}), "utf-8")
    return domain


def test_a_domain_kind_that_is_a_constituent_gets_the_theory_through_the_ordinary_compiler(tmp_path):
    """The binding that runs today, without view lowering: a domain pins the theory, and a kind of its own is
    a Constituent (is_a). Its elements are in the theory's tables, so the rules and axioms hold for them."""
    from rede_compiler import batch, scenarios

    domain = bound(tmp_path, [{"id": "whole", "title": "W"}, {"id": "half", "title": "H", "part_of": "whole", "repeat": 2},
                              {"id": "piece", "title": "P", "part_of": "half", "repeat": 3}])
    model = pack.read(domain)
    assert model.kinds["piece"].parent == "constituent" and model.meta["theory"] is False
    prog = ir.load(model.rules)
    (_, rows), = scenarios.states(model, domain)
    con = batch.connect(prog, scenarios.rule_rows(model, prog, rows))
    batch.compute(con, prog)
    got = as_text(batch.read(con, prog))
    assert got["within"] == {("half", "whole"), ("piece", "half"), ("piece", "whole")}
    assert got["outermost"] == {("half", "whole"), ("piece", "whole")} and got["part_cycle"] == set()


NODES = st.sampled_from("abcdefg")


@settings(max_examples=60)
@given(part_of=st.sets(st.tuples(NODES, NODES), max_size=12))
def test_axioms_and_rules_agree_with_the_reference_on_any_graph(part_of, tmp_path_factory):
    """Property (Hypothesis): on any finite graph every engine equals the reference. Where the axioms hold
    (no cycle, at most one direct whole) the parts are a forest: within is a strict partial order, the wholes
    of a part form a chain, and every part has exactly one outermost whole."""
    got = evaluate(sorted(part_of), tmp_path_factory.mktemp("part"))
    functional = len({x for x, _ in part_of}) == len(part_of)
    if functional and not got["part_cycle"]:
        within = got["within"]
        assert all((w, x) not in within for x, w in within)                              # asymmetric, so strict
        assert all((x, v) in within for x, w in within for w2, v in within if w == w2)   # transitive
        wholes = {}
        for x, w in within:
            wholes.setdefault(x, set()).add(w)
        for above in wholes.values():                                                    # a chain: all comparable
            assert all(a == b or (a, b) in within or (b, a) in within for a in above for b in above)
        assert sorted(x for x, _ in got["outermost"]) == sorted(x for (x,) in got["has_whole"])   # exactly one each
