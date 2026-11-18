"""Compare every example's compiled rule representations and check source order against a hand-written contract."""

from contextlib import closing
import json
import shutil
from pathlib import Path

import pytest
import yaml

from rezono_compiler import batch, emit, facts, pack, rules
from support import FIXTURE, REPO

ROOT = Path(__file__).resolve().parent
EXAMPLES = sorted(meta.parent for meta in ROOT.rglob("pack.yaml") if (meta.parent / "rules").is_dir())


def rules_of(folder):
    files = emit.compile_pack(pack.read(folder))
    ir = json.loads(files["ir/rules.json"])
    bundle = json.loads(files["bundle/schema-bundle.json"])
    return {r["id"]: r for r in ir["rules"]}, {r["id"]: r for r in bundle["rules"]}


def values(terms):
    return [t["value"] for t in terms]


@pytest.fixture
def sample(tmp_path):
    folder = tmp_path / "minimal"
    shutil.copytree(FIXTURE, folder)
    (folder / "rules").mkdir()
    source = """\
.decl size(a: symbol, s: number)
size(a,s) :- alpha__size(a,s).
.decl frozen(a: symbol)
frozen(a) :- beta__alpha(_,a).
.decl label(a: symbol, value: symbol)
label(a,v) :- alpha__title(a,v).
.decl big(a: symbol, d: number)
big(a,d) :- size(a,s), s >= 5, !frozen(a), d = s - 5, label(a,"large").
.decl order(a: symbol)
order(a) :- alpha__title(_,a).
.decl line(a: symbol, amount: number)
line(a,c) :- alpha__title(id,a), alpha__size(id,c).
.decl total(a: symbol, n: number, t: number)
total(a,n,t) :- order(a), n = count : { line(a,_) }, t = sum amount : { line(a,amount) }.
"""
    (folder / "rules/core.dl").write_text(source, encoding="utf-8")
    return folder


def test_mixed_and_aggregate_bodies_match_hand_written_contracts(sample):
    _, bundle = rules_of(sample)
    cases = REPO / "contracts/fixtures/bundle/Rule/valid"
    for name, file in [("big", "body-in-source-order.yaml"), ("total", "aggregates.yaml")]:
        expected = yaml.safe_load((cases / file).read_text("utf-8"))
        actual, = [r for r in bundle.values() if r["head"]["relation"] == name]
        assert actual["head"] == expected["head"]
        assert actual["body"] == expected["body"]


def test_mixed_and_aggregate_rules_on_four_rows(sample):
    model = pack.read(sample)
    prog = rules.load(model.rules)
    rows = facts.rows_of(model, {"alpha": [
        {"id": "a", "title": "large", "size": 7}, {"id": "b", "title": "large", "size": 8},
        {"id": "c", "title": "large", "size": 4}, {"id": "d", "title": "small", "size": 6},
    ], "beta": [{"id": "freeze-b", "alpha": "b"}]})
    conn, _, _ = batch.run(model, prog, rows)
    with closing(conn):
        actual = batch.read(conn, prog, ["big", "total"])
    # Only a passes the size, freeze and label checks. The large group sums to 7+8+4.
    assert actual == {"big": {("a", "2")}, "total": {("large", "3", "19"), ("small", "1", "6")}}


@pytest.mark.parametrize("folder", EXAMPLES, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_every_rule_body_is_the_rule_ir_in_source_order(folder):
    ir, bundle = rules_of(folder)
    assert ir, folder.name
    assert sorted(bundle) == sorted(ir)
    for rid, r in ir.items():
        b = bundle[rid]
        body = b["body"]
        assert b["head"]["relation"] == r["head"]["relation"] and values(b["head"]["terms"]) == r["head"]["terms"], rid
        assert [x["position"] for x in body] == list(range(1, len(body) + 1)), rid

        def of(kind):
            return [x for x in body if x["kind"] == kind]

        assert [(x["relation"], values(x["terms"]), x["polarity"]) for x in of("atom")] == [
            (a["relation"], a["terms"], a["polarity"]) for a in r["body"]], rid
        assert [(x["relation"], values(x["terms"]), x["function"], x.get("over"), x["result"]["value"],
                 x["aggregate_position"]) for x in of("aggregate")] == [
            (a["relation"], a["terms"], a["function"], a.get("over"), a["as"], i)
            for i, a in enumerate(r.get("aggregates", []))], rid
        assert [(x["op"], values(x["terms"]), x["result"]["value"]) for x in of("assignment")] == [
            (a["op"], [a["left"], a["right"]], a["var"]) for a in r.get("assignments", [])], rid
        assert [(x["op"], values(x["terms"])) for x in of("comparison")] == [
            (c["op"], [c["left"], c["right"]]) for c in r.get("conditions", [])], rid
        assert all(x["polarity"] == "positive" for x in body if x["kind"] != "atom"), rid
        # every term is typed, and a variable has the type the bundle gives it
        types = {v["name"]: v["type"] for v in b.get("variables", [])}
        terms = [*b["head"]["terms"], *(t for x in body for t in [*x["terms"], *([x["result"]] if "result" in x else [])])]
        for t in terms:
            assert t["kind"] == ("variable" if t["value"].startswith("?") else "wildcard" if t["value"] == "_"
                                 else "constant"), (rid, t)
            if t["kind"] == "variable":
                assert t["type"] == types[t["value"]], (rid, t)
