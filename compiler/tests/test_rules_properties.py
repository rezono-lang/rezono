"""Property tests of the rule compiler on generated rule programs (from the M2 probe).

The oracle is Soufflé, as a set (tests skip without `souffle`). Proofs are checked by the independent
checker (checker/). The contract checks need `linkml-validate` (the package `linkml`).
"""

import copy
import decimal
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from hypothesis import given, settings
from hypothesis import strategies as st

import rulegen as gen
import souffle
from rezono_compiler import batch as duck
from rezono_compiler import explain
from rezono_compiler import rules as ir
from rezono_compiler import rules_sql as sql
from rezono_compiler import rules_split
from support import part_program, typed

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "contracts" / "fixtures"
RULES = FIXTURES / "rules"
SOUFFLE = pytest.mark.skipif(shutil.which("souffle") is None, reason="needs souffle (the oracle)")
LINKML = pytest.mark.skipif(shutil.which("linkml-validate") is None, reason="needs linkml-validate")
# Soufflé runs once per example; fewer examples than the cheap properties.
ORACLE = settings(max_examples=min(settings().max_examples, 150))


def validate(path, schema="rules", cls="RuleProgram"):
    return subprocess.run(["linkml-validate", "-s", str(ROOT / "contracts" / f"{schema}.yaml"), "-C", cls, str(path)],
                          capture_output=True, text=True)


@LINKML
@pytest.mark.parametrize("path", sorted(RULES.glob("rejected/*.yaml")), ids=lambda p: p.name)
def test_rejected_rules_pass_the_schema(path):
    assert validate(path).returncode == 0, validate(path).stdout


@pytest.mark.parametrize("path", sorted(RULES.glob("rejected/*.yaml")), ids=lambda p: p.name)
def test_compiler_rejects_with_the_named_error(path):
    with pytest.raises(ir.IRError) as e:
        ir.load(yaml.safe_load(path.read_text()))
    assert e.value.code == path.stem.split("--")[0]   # <code>--<case>.yaml for a second case of one code


@pytest.mark.parametrize("path", sorted(RULES.glob("RuleProgram/valid/*.yaml")), ids=lambda p: p.name)
def test_compiler_accepts_valid(path):
    ir.load(yaml.safe_load(path.read_text()))


def freshness_problem(doc):
    """What the schema cannot say: a stale or pending value is shown as unknown."""
    if doc["freshness"] in ("stale", "pending") and doc["value"]["state"] != "unknown":
        return "stale_shows_value"
    return None


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("freshness/FreshValue/valid/*.yaml"))
                         + sorted(FIXTURES.glob("freshness/rejected/*.yaml")), ids=lambda p: f"{p.parent.name}/{p.name}")
def test_freshness_never_lies(path):
    want = path.stem if path.parent.name == "rejected" else None
    assert freshness_problem(yaml.safe_load(path.read_text())) == want


@LINKML
@pytest.mark.parametrize("n", [3, 17, 60])
def test_generated_programs_satisfy_the_contract(n, tmp_path):
    doc = gen.program(n, n, shapes=gen.ALL_SHAPES)
    (tmp_path / "p.yaml").write_text(yaml.safe_dump(doc))
    assert validate(tmp_path / "p.yaml").returncode == 0


@given(seed=st.integers(0, 10**6), n=st.integers(1, 80))
def test_generation_is_deterministic_and_checked(seed, n):
    a, b = gen.program(seed, n, shapes=gen.ALL_SHAPES), gen.program(seed, n, shapes=gen.ALL_SHAPES)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    prog = ir.load(a)
    assert len(prog.derived()) == n
    assert sql.feldera(prog) == sql.feldera(ir.load(b))


@given(seed=st.integers(0, 10**6), n=st.integers(2, 40), data=st.data())
def test_negation_through_recursion_is_rejected(seed, n, data):
    """Let a relation also negate a unary relation that reads it: then no stratification exists."""
    doc = gen.program(seed, n)
    prog = ir.load(doc)
    pairs = [(a, b) for a in prog.derived() for b in sorted(prog.downstream({a}))
             if [c.type for c in prog.relations[b].key] == ["string"]]
    if not pairs:
        return
    low, high = data.draw(st.sampled_from(pairs))
    doc = copy.deepcopy(doc)
    rule = next(r for r in doc["rules"] if r["head"]["relation"] == low)
    rule["body"].append({"relation": high, "terms": [rule["body"][0]["terms"][0]], "polarity": "negative",
                         "stratum": "0"})
    rule.pop("witness")
    with pytest.raises(ir.IRError) as e:
        ir.with_strata(doc)
    assert e.value.code == "not_stratified"


@SOUFFLE
@ORACLE
@given(seed=st.integers(0, 10**6), n=st.integers(1, 40), rows=st.integers(10, 400), degree=st.sampled_from([1, 3, 10]))
def test_duckdb_sql_equals_souffle_as_sets(seed, n, rows, degree, tmp_path_factory):
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    data = gen.facts(doc, seed, rows, domain=max(1, rows // degree))
    con = duck.connect(prog, data)
    duck.compute(con, prog, witnesses=True)
    assert duck.read(con, prog) == souffle.run(prog, data, tmp_path_factory.mktemp("s"))
    # the witnesses are complete and sound: their conclusions are exactly the relation
    got = duck.read(con, prog)
    for name in prog.derived():
        derived = set()
        for r in prog.rules_for(name):
            cols = sql.witness_columns(r)
            for row in con.execute(f'SELECT * FROM "{r.witness_relation}"').fetchall():
                theta = {v: str(x) for v, x in zip(r.variables, row)}
                assert len(cols) == len(row)
                derived.add(tuple(theta[t] if ir.is_var(t) else t for t in r.head.terms))
        assert derived == got[name], name


@given(seed=st.integers(0, 10**6), n=st.integers(1, 30), steps=st.integers(1, 6))
def test_reached_only_recompute_equals_full_recompute(seed, n, steps):
    """What DuckDB recomputes after a change (only what the change reaches) gives the full result."""
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    data = gen.facts(doc, seed, 200)
    a, b = duck.connect(prog, data), duck.connect(prog, data)
    duck.compute(a, prog)
    duck.compute(b, prog)
    for s in range(steps):
        rel, row, op = gen.change(doc, data, seed + s, 200)
        data[rel] = [r for r in data[rel] if r != row] + ([row] if op == "insert" else [])
        duck.apply(a, prog, rel, row, op)
        duck.apply(b, prog, rel, row, op)
        duck.compute(a, prog, relations=prog.downstream({rel}))
        duck.compute(b, prog)
        assert duck.read(a, prog) == duck.read(b, prog)


def test_regression_slow_negation_cycle_is_rejected():
    """Found by Hypothesis (seed 14, n 11): d0 negates d10, which reads d0 over five relations. The
    strata grow by one per pass, so a fixed number of passes accepted it; only a fixpoint rejects it."""
    doc = gen.program(14, 11)
    rule = next(r for r in doc["rules"] if r["head"]["relation"] == "d0")
    rule["body"].append({"relation": "d10", "terms": [rule["body"][0]["terms"][0]], "polarity": "negative",
                         "stratum": "0"})
    rule.pop("witness")
    with pytest.raises(ir.IRError) as e:
        ir.with_strata(doc)
    assert e.value.code == "not_stratified"


def small_program(relations, rules):
    """A hand-written rule program: strata and witnesses are filled in by the compiler."""
    return ir.with_strata({"format": ir.FORMAT, "pack": "test", "relations": relations,
                           "rules": [dict(r, module="m", origin={"file": "t.dl", "line": "1"}) for r in rules]})


@given(seed=st.integers(0, 10**6), n=st.integers(1, 30), rows=st.integers(10, 200), degree=st.sampled_from([1, 3]),
       pick=st.randoms(use_true_random=False))
def test_every_proof_is_valid_and_acyclic(seed, n, rows, degree, pick):
    """The explainer's proof of a derived row passes the independent checker (which also rejects cycles)."""
    from rezono_checker.check import check
    from rezono_checker.rules import load_rules

    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    data = gen.facts(doc, seed, rows, domain=max(1, rows // degree))
    con = duck.connect(prog, data)
    duck.compute(con, prog)
    derived = duck.read(con, prog)
    rows_ = duck.read(con, prog, [n for n, r in prog.relations.items() if r.role == "base"]) | derived
    ex = explain.Explainer(prog, rows_, duck.witnesses(con, prog))
    snaps = {r: ex.snapshot(r).encode() for r in prog.relations}
    manifest = {"id": "m", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                          "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}
    rules = load_rules(doc)
    every = sorted((r, k) for r in derived for k in derived[r])
    for rel, key in pick.sample(every, min(len(every), 25)):
        proof = ex.proof(rel, key, "m")
        report = check(proof, manifest, rules, lambda uri: snaps[uri])
        assert report["valid"], (rel, key, report["findings"][:5])
        assert all(f["reason"] != "unreachable_witness" for f in report["findings"])


def check_partition(prog, parts, budget):
    """Every relation once, a recursive core whole, within budget, and only earlier parts read.
    A part above the budget holds one relation that is not recursive, and is what `over_budget` reports.
    A part may be empty only in the middle (a place kept from a previous partition)."""
    assert sorted(x for p in parts for x in p) == sorted(prog.derived())
    assert not parts or parts[-1]
    owner = {x: i for i, p in enumerate(parts) for x in p}
    for core in rules_split.cores(prog):
        assert len({owner[x] for x in core}) == 1, core
    over = []
    for i, p in enumerate(parts):
        if sum(sql.views(prog, x) for x in p) > budget:
            assert len(p) == 1 and not prog.recursive(p[0]), p
            over.append((p[0], sql.views(prog, p[0])))
        assert all(owner[d] <= i for x in p for d in prog.deps(x) if d in owner)
    assert rules_split.over_budget(prog, parts, budget) == over


@given(seed=st.integers(0, 10**6), n=st.integers(1, 120), budget=st.integers(2, 40))
def test_the_partition_holds_e6(seed, n, budget):
    prog = ir.load(gen.program(seed, n, shapes=gen.ALL_SHAPES))
    largest = max((sum(sql.views(prog, x) for x in c) for c in rules_split.cores(prog)
                   if len(c) > 1 or prog.recursive(c[0])), default=0)
    if largest > budget:             # only a recursive core that is on its own above the budget blocks
        with pytest.raises(rules_split.TooBig):
            rules_split.partition(prog, budget)
        return
    parts = rules_split.partition(prog, budget)
    check_partition(prog, parts, budget)
    assert parts == rules_split.partition(prog, budget)          # deterministic
    if sum(sql.views(prog, x) for x in prog.derived()) <= budget:
        assert len(parts) == 1                                   # one pipeline whenever it fits


@settings(max_examples=min(settings().max_examples, 60))
@given(seed=st.integers(0, 10**6), n=st.integers(2, 40), budget=st.integers(4, 16), rows=st.integers(10, 150))
def test_every_partition_computes_what_one_pipeline_computes(seed, n, budget, rows):
    """Part by part, each reading only its inputs and what earlier parts export, gives the same sets."""
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    try:
        parts = rules_split.partition(prog, budget)
    except rules_split.TooBig:
        return
    data = gen.facts(doc, seed, rows)
    con = duck.connect(prog, data)
    duck.compute(con, prog)
    whole = duck.read(con, prog)
    known = {k: v for k, v in data.items()}
    got = {}
    for names in parts:
        sub = part_program(prog, names)
        inputs = {r: typed(prog, r, known[r]) for r, rel in sub.relations.items() if rel.role == "base" and r in known}
        c = duck.connect(sub, inputs)
        duck.compute(c, sub)
        for r, rows_ in duck.read(c, sub).items():
            got[r] = rows_
            known[r] = sorted(rows_)
    assert got == whole


@given(seed=st.integers(0, 10**6), n=st.integers(2, 80), budget=st.integers(4, 30), data=st.data())
def test_a_small_change_moves_no_view_given_the_previous_cut(seed, n, budget, data):
    """With the previous partition, adding or removing a relation that nothing reads moves no other view."""
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    if max(sum(sql.views(prog, x) for x in c) for c in rules_split.cores(prog)) > budget:
        return
    before = rules_split.partition(prog, budget)
    # add a leaf: a copy of an existing relation, in an existing or a new module
    src = data.draw(st.sampled_from(prog.derived()))
    rel = prog.relations[src]
    module = data.draw(st.sampled_from(sorted({r.module for r in prog.relations.values() if r.module} | {"mnew"})))
    terms = [f"?v{i}" for i in range(len(rel.key))]
    grown = copy.deepcopy(doc)
    grown["relations"].append({"name": "leaf", "role": "derived", "module": module, "explain": "materialize",
                               "key": [{"name": c.name, "type": c.type} for c in rel.key]})
    grown["rules"].append({"id": "leaf", "module": module, "head": {"relation": "leaf", "terms": terms},
                           "body": [{"relation": src, "terms": terms, "polarity": "positive"}],
                           "origin": {"file": f"rules/{module}.dl", "line": "1"}})
    for r in grown["rules"]:
        r.pop("witness", None)
    big = ir.load(ir.with_strata(grown))
    after = rules_split.partition(big, budget, previous=before)
    check_partition(big, after, budget)
    # every part keeps its relations (the order inside a part may follow the new evaluation order)
    assert [set(p) - {"leaf"} for p in after if p != ["leaf"]] == [set(p) for p in before]
    # and back: removing the leaf again restores the earlier cut
    assert [set(p) for p in rules_split.partition(prog, budget, previous=after)] == [set(p) for p in before]


# Costly (a database per part, every epoch recomputed), so fewer examples than the other properties.
@settings(max_examples=min(settings().max_examples, 25))
@given(seed=st.integers(0, 10**6), n=st.integers(4, 30), budget=st.integers(3, 10), steps=st.integers(1, 6))
def test_changes_cross_parts_through_the_export_stream(seed, n, budget, steps):
    """Review of #34: the real data path between parts. Each part runs on its own (DuckDB); after every
    change the generated export query of a producing part is read as the relay reads it: deletes and
    inserts since the previous epoch, decoded and applied to the import tables of its readers. A delete
    that crosses a boundary can bring a count to 0 or switch a negation on. The parts together must
    then equal one pipeline over the same facts."""
    doc = gen.program(seed, n, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    try:
        parts = rules_split.partition(prog, budget)
    except rules_split.TooBig:
        return
    if len(parts) < 2:
        return
    plan = rules_split.plan(prog, parts)
    data = gen.facts(doc, seed, 80)
    subs = [part_program(prog, p["views"]) for p in plan]
    cons = [duck.connect(sub, {r: data[r] for r in p["bases"] if r in data}) for sub, p in zip(subs, plan)]
    for con, p in zip(cons, plan):
        if p["exports"]:
            con.execute(f"CREATE TABLE {sql.q(rules_split.EPOCH)} (e BIGINT NOT NULL)")
    exported = [set() for _ in plan]

    def epoch():
        for k, (sub, p, con) in enumerate(zip(subs, plan, cons)):
            duck.compute(con, sub)
            if not p["exports"]:
                continue
            rows = {r for r in con.execute(rules_split.export_select(prog, p)).fetchall() if r[0] != "#epoch"}
            for op, changed in (("delete", exported[k] - rows), ("insert", rows - exported[k])):
                for row in sorted(changed):
                    values = rules_split.decode(prog, row[0], row[1:])
                    for j, q in enumerate(plan):
                        if row[0] in q["imports"]:
                            duck.apply(cons[j], subs[j], row[0], values, op)
            exported[k] = rows

    def same_as_one_pipeline():
        whole = duck.connect(prog, data)
        duck.compute(whole, prog)
        got = {}
        for sub, con in zip(subs, cons):
            got |= duck.read(con, sub)
        assert got == duck.read(whole, prog)

    epoch()
    same_as_one_pipeline()
    for s in range(steps):
        rel, row, op = gen.change(doc, data, seed + s, 80)
        data[rel] = [r for r in data[rel] if r != row] + ([row] if op == "insert" else [])
        for j, p in enumerate(plan):
            if rel in p["bases"]:
                duck.apply(cons[j], subs[j], rel, row, op)
        epoch()
        same_as_one_pipeline()


def test_count_and_sum_over_one_group_have_their_own_evidence():
    """Review of #13: two aggregates over the same relation and group are told apart by position."""
    from rezono_checker.check import check
    from rezono_checker.rules import load_rules

    doc = small_program(
        [{"name": "entry", "role": "base", "key": [{"name": "id", "type": "string"}]},
         {"name": "line", "role": "base", "key": [{"name": "entry", "type": "string"}, {"name": "line", "type": "string"},
                                                   {"name": "amount", "type": "integer"}]},
         {"name": "stats", "role": "derived", "module": "m", "explain": "materialize",
          "key": [{"name": "e", "type": "string"}, {"name": "n", "type": "integer"}, {"name": "t", "type": "integer"}]}],
        [{"id": "stats", "head": {"relation": "stats", "terms": ["?e", "?n", "?t"]},
          "body": [{"relation": "entry", "terms": ["?e"], "polarity": "positive"}],
          "aggregates": [{"relation": "line", "terms": ["?e", "_", "_"], "function": "count", "as": "?n"},
                         {"relation": "line", "terms": ["?e", "_", "_"], "function": "sum", "over": "amount", "as": "?t"}]}])
    prog = ir.load(doc)
    data = {"entry": [["e1"]], "line": [["e1", "a", 7], ["e1", "b", 7], ["e1", "c", 1]]}
    con = duck.connect(prog, data)
    duck.compute(con, prog)
    derived = duck.read(con, prog)
    assert derived["stats"] == {("e1", "3", "15")}
    ex = explain.Explainer(prog, duck.read(con, prog, ["entry", "line"]) | derived, duck.witnesses(con, prog))
    snaps = {r: ex.snapshot(r).encode() for r in prog.relations}
    manifest = {"id": "m", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                          "sha256": hashlib.sha256(b).hexdigest()} for r, b in sorted(snaps.items())]}
    proof = ex.proof("stats", ("e1", "3", "15"), "m")
    assert [a["position"] for a in proof["witnesses"][0]["aggregates"]] == [0, 1]
    report = check(proof, manifest, load_rules(doc), lambda uri: snaps[uri])
    assert report["valid"] and not report["findings"], report["findings"]


def same_as_souffle(doc, data, tmp_path):
    prog = ir.load(doc)
    con = duck.connect(prog, data)
    duck.compute(con, prog, witnesses=True)
    got = duck.read(con, prog)
    assert got == souffle.run(prog, data, tmp_path)
    return prog, con, got


@SOUFFLE
@pytest.mark.parametrize("hours", [[], [["ann", "t1", "5"], ["bob", "t2", "3"]]], ids=["empty", "two"])
def test_global_min_over_nothing_has_no_conclusion(hours, tmp_path):
    doc = small_program(
        [{"name": "flag", "role": "base", "key": [{"name": "id", "type": "string"}]},
         {"name": "hours", "role": "base", "key": [{"name": "m", "type": "string"}, {"name": "t", "type": "string"}],
          "values": [{"name": "h", "type": "integer"}]},
         {"name": "lowest", "role": "derived", "module": "m", "explain": "on_demand",
          "key": [{"name": "f", "type": "string"}, {"name": "h", "type": "integer"}]}],
        [{"id": "lowest", "head": {"relation": "lowest", "terms": ["?f", "?x"]},
          "body": [{"relation": "flag", "terms": ["?f"], "polarity": "positive"}],
          "aggregates": [{"relation": "hours", "terms": ["_", "_"], "function": "min", "over": "h", "as": "?x"}]}])
    _, _, got = same_as_souffle(doc, {"flag": [["on"]], "hours": hours}, tmp_path)
    assert got["lowest"] == (set() if not hours else {("on", "3")})


@SOUFFLE
@pytest.mark.parametrize("p", [[["a"]], [["b"]]], ids=["holds", "fails"])
def test_rule_without_variables_has_the_empty_substitution(p, tmp_path):
    doc = small_program(
        [{"name": "p", "role": "base", "key": [{"name": "id", "type": "string"}]},
         {"name": "d", "role": "derived", "module": "m", "explain": "materialize", "key": [{"name": "id", "type": "string"}]}],
        [{"id": "d_a", "head": {"relation": "d", "terms": ["a"]},
          "body": [{"relation": "p", "terms": ["a"], "polarity": "positive"}]}])
    prog, con, got = same_as_souffle(doc, {"p": p}, tmp_path)
    rows = con.execute(f'SELECT * FROM "{prog.rules["d_a"].witness_relation}"').fetchall()
    assert rows == ([(True,)] if p == [["a"]] else [])
    assert got["d"] == ({("a",)} if rows else set())



@pytest.mark.parametrize("cond, ok", [({"op": "eq", "left": "a", "right": "a"}, True),
                                      ({"op": "lt", "left": "1", "right": "2"}, True),
                                      ({"op": "lt", "left": "a", "right": "b"}, False)],
                         ids=["string-eq", "integer-lt", "string-lt"])
def test_conditions_between_constants(cond, ok):
    """Two constants are typed by their own form; order comparisons still need integers."""
    rels = [{"name": "p", "role": "base", "key": [{"name": "id", "type": "string"}]},
            {"name": "d", "role": "derived", "module": "m", "explain": "materialize", "key": [{"name": "id", "type": "string"}]}]
    rule = {"id": "d_a", "head": {"relation": "d", "terms": ["a"]},
            "body": [{"relation": "p", "terms": ["a"], "polarity": "positive"}], "conditions": [cond]}
    if ok:
        small_program(rels, [rule])
    else:
        with pytest.raises(ir.IRError) as e:
            small_program(rels, [rule])
        assert e.value.code == "bad_condition"

ROUNDING = {"round": decimal.ROUND_HALF_UP, "floor": decimal.ROUND_FLOOR, "ceil": decimal.ROUND_CEILING}


@pytest.mark.parametrize("case", yaml.safe_load((FIXTURES / "calc/rounding/cases.yaml").read_text())["cases"],
                         ids=lambda c: f"{c['op']}({c['n']}/{c['d']})")
def test_rounding_cases_agree_with_decimal(case):
    """The rounding of calc.yaml, against Python's decimal module as an independent oracle."""
    with decimal.localcontext() as ctx:
        ctx.prec = 60
        x = decimal.Decimal(case["n"]) / decimal.Decimal(case["d"])
        got = x.quantize(decimal.Decimal(1), rounding=ROUNDING[case["op"]])
    assert str(int(got)) == case["want"]


def _divisions(prog):
    return sum(s.op == "div" for r in prog.rules.values() for s in r.assignments)


def _wholes(prog):
    """The rules whose body is only aggregates."""
    return sum(not r.body for r in prog.rules.values())


@pytest.mark.parametrize("pick", [0, 1])
def test_feldera_runs_generated_programs_as_duckdb_does(pick, tmp_path):
    """E10: Feldera is the reference. A generated program with every shape, integer division with negative
    operands and a body of aggregates only among them, on a running Feldera (FELDERA_URL; the label `feldera`), with a witness view per rule
    (the explain SQL): after the facts and after each single-fact change, every relation and every witness
    equals the batch backend (DuckDB, which divides with rezono_quotient), and Soufflé where it is installed."""
    from feldera import URL, deploy, processed, push, query, stop
    if not URL:
        pytest.skip("set FELDERA_URL to a running Feldera")
    seed = [s for s in range(500) for p in [ir.load(gen.program(s, 14, shapes=gen.ALL_SHAPES))]
            if _divisions(p) >= 2 and _wholes(p) >= 1][pick]
    doc = gen.program(seed, 14, shapes=gen.ALL_SHAPES)
    prog = ir.load(doc)
    data = gen.facts(doc, seed, 60, domain=20)
    columns = {n: [c.name for c in r.key + r.values] for n, r in prog.relations.items() if r.role == "base"}
    name = f"rezono-rules-generated-{pick}"
    deploy(name, sql.feldera(prog, witnesses=True), profile="unoptimized", workers=2)

    def send(rows, op):
        updates = {}
        for rel, rs in rows.items():
            updates.setdefault(rel, []).extend({op: dict(zip(columns[rel], r))} for r in rs)
        processed(name, push(name, updates))

    def same():
        con = duck.connect(prog, data)
        duck.compute(con, prog, witnesses=True)
        want = duck.read(con, prog)
        for rel in prog.derived():
            cols = [c.name for c in prog.relations[rel].key]
            assert {tuple(str(r[c]) for c in cols) for r in query(name, f'SELECT * FROM "{rel}"')} == want[rel], rel
            for r in prog.rules_for(rel):
                cols = sql.witness_columns(r)
                table = f'SELECT * FROM "{r.witness_relation}"'
                got = {tuple(str(x[c]) for c in cols) for x in query(name, table)}
                assert got == {tuple(str(v) for v in x) for x in con.execute(table).fetchall()}, r.id
        if shutil.which("souffle"):
            assert souffle.run(prog, data, tmp_path) == want

    send({rel: rows for rel, rows in data.items() if rows}, "insert")
    same()
    for s in range(3):
        rel, row, op = gen.change(doc, data, seed + s, 20)
        data[rel] = [r for r in data[rel] if r != row] + ([row] if op == "insert" else [])
        send({rel: [row]}, op)
        same()
    stop(name)
