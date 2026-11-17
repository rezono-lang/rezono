"""MOD14: the rule bodies of the schema bundle, held against the rule IR of the same golden, for every rule of
every example. The bundle gives one body in source order; filtered per kind it is the IR's four lists, in their
order, with the same terms. Light: it reads the goldens only."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent
PAIRS = sorted(p.parents[1] for p in ROOT.glob("**/expected/compiled/ir/rules.json")
               if (p.parents[1] / "bundle" / "schema-bundle.json").is_file())


def rules_of(compiled):
    ir = {r["id"]: r for r in json.loads((compiled / "ir" / "rules.json").read_text("utf-8"))["rules"]}
    bundle = {r["id"]: r for r in json.loads((compiled / "bundle" / "schema-bundle.json").read_text("utf-8"))["rules"]}
    return ir, bundle


def values(terms):
    return [t["value"] for t in terms]


def test_examples_with_rules_are_found():
    assert PAIRS


@pytest.mark.parametrize("compiled", PAIRS, ids=lambda p: p.parents[1].relative_to(ROOT).as_posix())
def test_every_rule_body_is_the_rule_ir_in_source_order(compiled):
    ir, bundle = rules_of(compiled)
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
