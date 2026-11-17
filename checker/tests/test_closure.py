"""RV-K01: the closure pass. Every witness below is a correct proof, so only the missing row can refuse the epoch:
an engine that fails to derive a row leaves snapshots in which each negation and aggregate over it still checks.
Hand-written rule IR, so nothing here depends on the compiler."""

import hashlib
import json
from dataclasses import replace

import pytest

from rezono_checker import closure
from rezono_checker.canon import encode_key
from rezono_checker.check import check_epoch
from rezono_checker.rules import derived_relations, load_rules


def relation(name, role, *columns, **flags):
    """A relation; a column named `n#` is an integer."""
    key = [{"name": c.removesuffix("#"), "type": "integer" if c.endswith("#") else "string"} for c in columns]
    return {"name": name, "role": role, "key": key, **flags}


def rule(rid, stratum, head, *body, **more):
    """A rule from atoms as tuples: ("flag", "?x"), or ("not", "blocked", "?x") for a negative premise."""
    literals = [{"relation": b[1] if b[0] == "not" else b[0], "terms": list(b[2:] if b[0] == "not" else b[1:]),
                 "polarity": "negative" if b[0] == "not" else "positive"} for b in body]
    return {"id": rid, "stratum": str(stratum), "head": {"relation": head[0], "terms": list(head[1:])},
            "body": literals, **more}


def aggregate(function, var, *atom, over=None):
    return {"relation": atom[0], "terms": list(atom[1:]), "function": function, "as": var,
            **({"over": over} if over else {})}


def program(relations, *rules):
    """A rule IR; each premise gets the stratum of its relation, as the rules themselves give it."""
    strata = {r["head"]["relation"]: r["stratum"] for r in rules}
    for r in rules:
        for part in (*r["body"], *r.get("aggregates", ())):
            part["stratum"] = strata.get(part["relation"], "0")
    return {"format": "rezono.rules/1", "pack": "example", "relations": list(relations), "rules": list(rules)}


def missing(doc, rows, read=(), values=None):
    """What closure.check reports on plain rows: (relation, key parts, rule), in report order."""
    def table(name):
        return {encode_key(k): (tuple(k), (values or {}).get((name, *k), {})) for k in rows.get(name, [])}
    return [(f["relation"], json.loads(f["key"]), f["rule"]) for f in closure.check(load_rules(doc), table, read)]


def witness(doc, rid, **theta):
    r = next(r for r in doc["rules"] if r["id"] == rid)

    def key(terms):
        return encode_key([theta[t[1:]] if t.startswith("?") else t for t in terms])
    return {"conclusion": {"relation": r["head"]["relation"], "key": key(r["head"]["terms"])}, "rule_id": rid,
            "bindings": [{"variable": f"?{v}", "value": x} for v, x in sorted(theta.items())],
            "premises": [{"row": {"relation": b["relation"], "key": key(b["terms"])}, "polarity": b["polarity"],
                          "stratum": int(b["stratum"])} for b in r["body"]]}


def epoch(doc, rows, witnesses, **kw):
    loaded = load_rules(doc)
    snaps = {r: json.dumps([{"key": k} for k in rs]).encode() for r, rs in rows.items()}
    manifest = {"id": "m-1", "snapshots": [{"relation": r, "role": "all", "complete": True, "uri": r, "format": "json",
                                            "sha256": hashlib.sha256(b).hexdigest()} for r, b in snaps.items()]}
    return check_epoch(witnesses, manifest, loaded, snaps.__getitem__, derived=derived_relations(doc, loaded), **kw)


def errors(report):
    return sorted((f["reason"], f.get("relation"), f.get("key")) for f in report["findings"] if f["severity"] == "error")


# --- one epoch, through check_epoch ---------------------------------------------------------------

FLAG, REQUEST = relation("flag", "base", "id"), relation("request", "base", "id")
GATE = program([FLAG, REQUEST, relation("blocked", "derived", "id"), relation("allowed", "derived", "id")],
               rule("blocked", 0, ("blocked", "?x"), ("flag", "?x")),
               rule("allowed", 1, ("allowed", "?x"), ("request", "?x"), ("not", "blocked", "?x")))


def test_a_row_the_engine_did_not_derive_makes_no_negation_valid():
    """The scenario of the ticket: flag(a) and no blocked(a). allowed(a) has a correct proof on these snapshots."""
    report = epoch(GATE, {"flag": [["a"]], "request": [["a"]], "blocked": [], "allowed": [["a"]]},
                   [witness(GATE, "allowed", x="a")])
    assert errors(report) == [("underived_row", "blocked", encode_key(["a"]))]
    (finding,) = report["findings"]
    assert (finding["rule"], finding["bindings"]) == ("blocked", [{"variable": "?x", "value": "a"}])


def test_the_model_itself_is_closed():
    report = epoch(GATE, {"flag": [["a"]], "request": [["a"], ["b"]], "blocked": [["a"]], "allowed": [["b"]]},
                   [witness(GATE, "blocked", x="a"), witness(GATE, "allowed", x="b")])
    assert report["valid"] and not report["findings"]


def test_a_relation_a_negated_relation_reads_is_covered_too():
    """blocked is closed over mid here, because mid(a) is missing as well: the gap is one relation further down."""
    doc = program([FLAG, REQUEST, *(relation(n, "derived", "id") for n in ("mid", "blocked", "allowed"))],
                  rule("mid", 0, ("mid", "?x"), ("flag", "?x")),
                  rule("blocked", 0, ("blocked", "?x"), ("mid", "?x")),
                  rule("allowed", 1, ("allowed", "?x"), ("request", "?x"), ("not", "blocked", "?x")))
    report = epoch(doc, {"flag": [["a"]], "request": [["a"]], "mid": [], "blocked": [], "allowed": [["a"]]},
                   [witness(doc, "allowed", x="a")])
    assert errors(report) == [("underived_row", "mid", encode_key(["a"]))]


def test_an_invariant_the_engine_left_empty_does_not_pass():
    """An invariant is the checker's own negation: it must be empty, so it must be complete."""
    doc = program([FLAG, relation("bad", "derived", "id", invariant=True)], rule("bad", 0, ("bad", "?x"), ("flag", "?x")))
    assert errors(epoch(doc, {"flag": [["a"]], "bad": []}, [])) == [("underived_row", "bad", encode_key(["a"]))]


def test_an_outcome_cannot_hide_a_second_state():
    """known and unknown for one element block (W7). Without the unknown row the outcome looks total and single."""
    doc = program([relation("host", "base", "id"), relation("ok", "base", "id"),
                   relation("state", "derived", "id", "state", "reason", outcome="host")],
                  rule("known", 0, ("state", "?x", "known", ""), ("host", "?x"), ("ok", "?x")),
                  rule("unknown", 0, ("state", "?x", "unknown", "unchecked"), ("host", "?x")))
    rows = {"host": [["h"]], "ok": [["h"]], "state": [["h", "known", ""]]}
    assert errors(epoch(doc, rows, [witness(doc, "known", x="h")])) == [
        ("underived_row", "state", encode_key(["h", "unknown", "unchecked"]))]


def test_a_relation_whose_absence_nothing_reads_is_not_recomputed():
    """The scope limit: a missing row of `seen` hides a conclusion and makes no other one false."""
    doc = program([FLAG, relation("seen", "derived", "id")], rule("seen", 0, ("seen", "?x"), ("flag", "?x")))
    assert closure.covered(load_rules(doc)) == set()
    assert epoch(doc, {"flag": [["a"]], "seen": []}, [])["valid"]


def test_what_the_calculation_reads_is_covered():
    """A calculation reads a missing row as false or unknown (calc.reads), so its relations are covered."""
    doc = program([FLAG, relation("as_of", "base", "id"), relation("seen", "derived", "id")],
                  rule("seen", 0, ("seen", "?x"), ("flag", "?x")))
    calc_ir = {"format": "rezono.calc-ir/1", "as_of": "as_of", "facts": [{"id": "f", "reads": "presence", "table": "seen"}],
               "rules": [], "versions": [{"id": "v@1", "view": "v__1", "definitions": [
                   {"when": {"fact": "f"}, "value": {"fact": "f"}}]}]}
    report = epoch(doc, {"flag": [["a"]], "as_of": [], "seen": []}, [], calc_ir=calc_ir)
    assert ("underived_row", "seen", encode_key(["a"])) in errors(report)


def test_a_role_is_not_held_to_closure():
    """A role's snapshots are filtered (O8): what it reads in full is checked against the complete epoch."""
    rows = {"flag": [["a"]], "request": [["a"]], "blocked": [], "allowed": [["a"]]}
    assert epoch(GATE, rows, [witness(GATE, "allowed", x="a")], full=set(rows))["valid"]


# --- which instances hold, through closure.check ---------------------------------------------------

def test_constants_and_repeated_variables_select_rows():
    doc = program([relation("link", "base", "a", "b"), relation("kind", "base", "id", "kind"),
                   relation("loop", "derived", "id"), relation("db", "derived", "id")],
                  rule("loop", 0, ("loop", "?x"), ("link", "?x", "?x")),
                  rule("db", 0, ("db", "?x"), ("kind", "?x", "db")))
    rows = {"link": [["a", "a"], ["a", "b"]], "kind": [["a", "db"], ["b", "app"], ["c", "db"]], "db": [["a"]]}
    assert missing(doc, rows, read={"loop", "db"}) == [("db", ["c"], "db"), ("loop", ["a"], "loop")]


def test_joins_follow_shared_variables_and_a_product_has_none():
    doc = program([relation("edge", "base", "a", "b"), relation("left", "base", "id"), relation("right", "base", "id"),
                   relation("two", "derived", "a", "b"), relation("pair", "derived", "a", "b")],
                  rule("two", 0, ("two", "?x", "?z"), ("edge", "?x", "?y"), ("edge", "?y", "?z")),
                  rule("pair", 0, ("pair", "?x", "?y"), ("left", "?x"), ("right", "?y")))
    rows = {"edge": [["a", "b"], ["b", "c"], ["b", "d"], ["x", "y"]], "left": [["l1"], ["l2"]], "right": [["r"]],
            "two": [["a", "c"]], "pair": [["l2", "r"]]}
    assert missing(doc, rows, read={"two", "pair"}) == [("pair", ["l1", "r"], "pair"), ("two", ["a", "d"], "two")]


def test_a_filter_is_applied_before_the_next_join(monkeypatch):
    """Review of #540 (P2): `a(x), b(y)` with a condition on x alone must not carry the whole product. Each
    condition and negation is applied as soon as its variables are bound, so the join sees what is left."""
    doc = program([relation("left", "base", "id"), relation("right", "base", "id"), relation("off", "base", "id"),
                   relation("pair", "derived", "a", "b")],
                  rule("pair", 1, ("pair", "?x", "?y"), ("left", "?x"), ("right", "?y"), ("not", "off", "?x"),
                       conditions=[{"op": "ne", "left": "?x", "right": "l1"}]))
    rows = {"left": [["l1"], ["l2"], ["l3"]], "right": [["r1"], ["r2"]], "off": [["l2"]]}
    carried, join = [], closure._join
    monkeypatch.setattr(closure, "_join", lambda a, b: carried.append(len(a[1])) or join(a, b))
    assert missing(doc, rows, read={"pair"}) == [("pair", ["l3", "r1"], "pair"), ("pair", ["l3", "r2"], "pair")]
    assert carried == [1, 1]  # the empty substitution into `left`; then l3 alone into `right`


def test_recursion_is_one_step_over_the_snapshot():
    """Closed means closed under one application of each rule: no fixpoint is computed here."""
    doc = program([relation("edge", "base", "a", "b"), relation("node", "base", "id"),
                   relation("reach", "derived", "a", "b"), relation("apart", "derived", "a", "b")],
                  rule("reach_edge", 0, ("reach", "?x", "?y"), ("edge", "?x", "?y")),
                  rule("reach_step", 0, ("reach", "?x", "?z"), ("reach", "?x", "?y"), ("edge", "?y", "?z")),
                  rule("apart", 1, ("apart", "?x", "?y"), ("node", "?x"), ("node", "?y"), ("not", "reach", "?x", "?y")))
    rows = {"edge": [["a", "b"], ["b", "c"], ["c", "d"]], "reach": [["a", "b"], ["b", "c"], ["c", "d"], ["a", "c"]]}
    assert missing(doc, rows) == [("reach", ["a", "d"], "reach_step"), ("reach", ["b", "d"], "reach_step")]
    rows["reach"] += [["a", "d"], ["b", "d"]]
    assert missing(doc, rows) == []


SIZES = program(
    [relation("team", "base", "id"), relation("member", "base", "team", "person"),
     relation("score", "base", "team", "round", "points#"), relation("weight", "base", "team", "item", values=[
         {"name": "kg", "type": "integer"}]),
     relation("size", "derived", "team", "n#"), relation("total", "derived", "team", "n#"),
     relation("best", "derived", "team", "n#"), relation("load", "derived", "team", "n#")],
    rule("size", 1, ("size", "?t", "?n"), ("team", "?t"), aggregates=[aggregate("count", "?n", "member", "?t", "_")]),
    rule("total", 1, ("total", "?t", "?n"), ("team", "?t"),
         aggregates=[aggregate("sum", "?n", "score", "?t", "_", "_", over="points")]),
    rule("best", 1, ("best", "?t", "?n"), ("team", "?t"),
         aggregates=[aggregate("max", "?n", "score", "?t", "_", "_", over="points")]),
    rule("load", 1, ("load", "?t", "?n"), ("team", "?t"),
         aggregates=[aggregate("sum", "?n", "weight", "?t", "_", over="kg")]))


def test_an_aggregate_binds_what_the_engine_gives():
    """count and sum of an empty group are 0 and give a head; min and max of one give no conclusion
    (contracts/rules.yaml). Two rows with the same value both count."""
    rows = {"team": [["empty"], ["t"]], "member": [["t", "p1"], ["t", "p2"]],
            "score": [["t", "r1", "7"], ["t", "r2", "7"], ["t", "r3", "-3"]]}
    assert missing(SIZES, rows, read={"size", "total", "best"}) == [
        ("best", ["t", "7"], "best"),
        ("size", ["empty", "0"], "size"), ("size", ["t", "2"], "size"),
        ("total", ["empty", "0"], "total"), ("total", ["t", "11"], "total")]


@pytest.mark.parametrize("cell, expected", [
    ({"state": "known", "value": "5"}, [("load", ["t", "8"], "load")]),
    ({"state": "not_applicable"}, [("load", ["t", "3"], "load")]),
    ({"state": "unknown"}, []),  # no bare integer to bind: no witness holds, so no row is owed
    ({"state": "invalid"}, []),  # invalid_value: the same
])
def test_an_aggregate_without_a_known_result_owes_no_row(cell, expected):
    rows = {"team": [["t"]], "weight": [["t", "a"], ["t", "b"]]}
    values = {("weight", "t", "a"): {"kg": {"state": "known", "value": "3"}}, ("weight", "t", "b"): {"kg": cell}}
    assert missing(SIZES, rows, read={"load"}, values=values) == expected


EXCESS = program(
    [relation("budget", "base", "id", "n#"), relation("over", "derived", "id", "excess#")],
    rule("over", 0, ("over", "?e", "?x"), ("budget", "?e", "?t"),
         conditions=[{"op": "gt", "left": "?t", "right": "10"}],
         assignments=[{"var": "?h", "op": "sub", "left": "?t", "right": "10"},
                      {"var": "?x", "op": "mul", "left": "?h", "right": "2"}]))


def test_conditions_filter_and_assignments_bind_in_dependency_order():
    rows = {"budget": [["low", "10"], ["high", "14"], ["text", "many"]]}
    assert missing(EXCESS, rows, read={"over"}) == [("over", ["high", "8"], "over")]


def test_arithmetic_outside_bigint_owes_no_row():
    """Every engine stops there, so no proof can pass it (arithmetic_overflow)."""
    assert missing(EXCESS, {"budget": [["huge", str(2**63 - 1)]]}, read={"over"}) == []
    assert missing(SIZES, {"team": [["t"]], "score": [["t", "r1", str(2**63 - 1)], ["t", "r2", "1"]]}, read={"total"}) == []


def test_a_calculation_selection_gives_a_rule_only_whole_numbers():
    """A fraction never reaches a rule (bad_calc_premise), so it owes no row."""
    doc = program([relation("share", "calc", "subject", "value#", "state", "reason", world="open"),
                   relation("noted", "derived", "subject", "value#", world="open")],
                  rule("noted", 0, ("noted", "?s", "?v"), ("share", "?s", "?v", "known", "")))
    rows = {"share": [["a", "3", "known", ""], ["b", "1/2", "known", ""], ["c", "", "unknown", "missing"]]}
    assert missing(doc, rows, read={"noted"}) == [("noted", ["a", "3"], "noted")]


def test_the_report_names_the_least_substitution_once_per_rule_and_row():
    doc = program([relation("edge", "base", "a", "b"), relation("source", "derived", "id")],
                  rule("source", 0, ("source", "?x"), ("edge", "?x", "?y")))
    findings = closure.check(load_rules(doc), lambda name: {encode_key(k): (tuple(k), {}) for k in
                                                           {"edge": [["a", "z"], ["a", "b"], ["c", "d"]]}.get(name, [])},
                             read={"source"})
    assert [(f["key"], f["bindings"]) for f in findings] == [
        (encode_key(["a"]), [{"variable": "?x", "value": "a"}, {"variable": "?y", "value": "b"}]),
        (encode_key(["c"]), [{"variable": "?x", "value": "c"}, {"variable": "?y", "value": "d"}])]


def test_a_rule_with_a_free_variable_cannot_be_enumerated():
    """`lonely(x) :- request(x), !pair(x, y)`: any y would do. The loader refuses such a rule (range restriction,
    test_rule_safety.py); the pass does not lean on that, and refuses it too rather than guess."""
    doc = program([REQUEST, relation("pair", "derived", "a", "b"), relation("lonely", "derived", "id"),
                   relation("calm", "derived", "id")],
                  rule("pair", 0, ("pair", "?x", "?x"), ("request", "?x")),
                  rule("lonely", 1, ("lonely", "?x"), ("request", "?x"), ("not", "pair", "?x", "?x")),
                  rule("calm", 2, ("calm", "?x"), ("request", "?x"), ("not", "lonely", "?x")))
    rules = load_rules(doc)
    negated = rules["lonely"].body[1]
    unsafe = replace(negated, atom=replace(negated.atom, terms=("?x", "?y")))
    rules["lonely"] = replace(rules["lonely"], body=(rules["lonely"].body[0], unsafe))
    with pytest.raises(ValueError, match=r"lonely: \?y is not bound"):
        closure.check(rules, lambda name: {encode_key(["a"]): (("a",), {})} if name == "request" else {})


# --- a body of aggregates only: one instance, without a group -------------------------------------

def totals(*rules):
    return program([FLAG, REQUEST, relation("flags", "derived", "n#"), relation("calm", "derived", "id")],
                   *rules, rule("calm", 2, ("calm", "?x"), ("request", "?x"), ("not", "flags", "0")))


COUNTED = totals(rule("flags", 1, ("flags", "?n"), aggregates=[aggregate("count", "?n", "flag", "_")]))


@pytest.mark.parametrize("flags, owed", [([], "0"), ([["a"], ["b"]], "2")], ids=["nothing", "two"])
def test_a_total_over_a_whole_relation_owes_its_one_row(flags, owed):
    """`flags(n) :- n = count : { flag(_) }` has no premise and no group: exactly one instance, also over
    nothing, where the count is 0. Without its row `calm` would hold for every request."""
    rows = {"flag": flags, "request": [["r"]]}
    assert missing(COUNTED, rows | {"flags": [], "calm": []}) == [("flags", [owed], "flags")]
    assert missing(COUNTED, rows | {"flags": [[owed]], "calm": []}) == []
    report = epoch(COUNTED, rows | {"flags": [], "calm": [["r"]]}, [witness(COUNTED, "calm", x="r")])
    assert ("underived_row", "flags", encode_key([owed])) in errors(report)


def test_a_minimum_over_nothing_owes_no_row():
    """An empty `min` or `max` has no result a binding can carry, so the rule has no instance; over rows it has one."""
    doc = totals(rule("flags", 1, ("flags", "?n"), aggregates=[aggregate("min", "?n", "size", "_", "_", over="n")]))
    doc["relations"].append(relation("size", "base", "id", "n#"))
    assert missing(doc, {"size": [], "request": [], "flags": [], "calm": []}) == []
    assert missing(doc, {"size": [["a", "4"], ["b", "3"]], "request": [], "flags": [], "calm": []}) == [
        ("flags", ["3"], "flags")]


# --- a counter with an explicit bound (RV-K18) ---------------------------------------

def counting(condition):
    """`depth(a, 0) :- seed(a).  depth(b, m) :- depth(a, n), <condition>, step(a, b), m = n + 1.`"""
    return program([relation("seed", "base", "id"), relation("step", "base", "a", "b"),
                    relation("depth", "derived", "id", "n#")],
                   rule("depth_start", 0, ("depth", "?a", "0"), ("seed", "?a")),
                   rule("depth_step", 0, ("depth", "?b", "?m"), ("depth", "?a", "?n"), ("step", "?a", "?b"),
                        conditions=[condition], assignments=[{"var": "?m", "op": "add", "left": "?n", "right": "1"}]))


DEPTH = counting({"op": "lt", "left": "?n", "right": "3"})  # read while n <= 2, so a row has at most n = 3
CHAIN = [["s", "a"], ["a", "b"], ["b", "c"]]


def reached(doc, rows):
    def table(name):
        return {encode_key(k): (tuple(k), {}) for k in rows.get(name, [])}
    return closure.exhausted(load_rules(doc), table)


def depths(*rows):
    return [[x, str(n)] for x, n in rows]


def test_a_count_that_ends_at_its_bound_is_whole():
    """The last row has n = 3 and nothing to step to: the bound is met, not passed."""
    rows = {"seed": [["s"]], "step": CHAIN, "depth": depths(("s", 0), ("a", 1), ("b", 2), ("c", 3))}
    assert reached(DEPTH, rows) == []


def test_a_snapshot_cut_at_the_bound_is_refused():
    """One step more: the engine stopped at c, n = 3, and the rule would add d and e at 4. The snapshot holds
    every row the rule as written derives, so only the bound refuses it, never `underived_row`."""
    rows = {"seed": [["s"]], "step": CHAIN + [["c", "d"], ["c", "e"]],
            "depth": depths(("s", 0), ("a", 1), ("b", 2), ("c", 3))}
    (finding,) = reached(DEPTH, rows)
    assert finding == {"reason": "bound_reached", "relation": "depth", "rule": "depth_step", "bound": "?n <= 2",
                       "count": 2, "key": encode_key(["d", "4"]),
                       "bindings": [{"variable": "?a", "value": "c"}, {"variable": "?b", "value": "d"},
                                    {"variable": "?m", "value": "4"}, {"variable": "?n", "value": "3"}]}
    proofs = [witness(DEPTH, "depth_start", a="s")] + [
        witness(DEPTH, "depth_step", a=a, b=b, n=str(n), m=str(n + 1)) for (a, b), n in zip(CHAIN, range(3))]
    assert errors(epoch(DEPTH, rows, proofs)) == [("bound_reached", "depth", encode_key(["d", "4"]))]
    whole = rows | {"step": CHAIN}
    assert epoch(DEPTH, whole, proofs)["valid"]


@pytest.mark.parametrize("condition", [{"op": "le", "left": "?n", "right": "2"}, {"op": "gt", "left": "3", "right": "?n"},
                                       {"op": "ge", "left": "2", "right": "?n"}], ids=["le", "gt", "ge"])
def test_every_spelling_of_the_bound_is_held(condition):
    rows = {"seed": [["s"]], "step": CHAIN + [["c", "d"]], "depth": depths(("s", 0), ("a", 1), ("b", 2), ("c", 3))}
    assert [(f["bound"], f["key"]) for f in reached(counting(condition), rows)] == [("?n <= 2", encode_key(["d", "4"]))]


def test_a_cycle_and_a_second_start_ahead_reach_the_bound_too():
    cycle = {"seed": [["s"]], "step": [["s", "a"], ["a", "b"], ["b", "a"]],
             "depth": depths(("s", 0), ("a", 1), ("b", 2), ("a", 3))}
    assert [f["key"] for f in reached(DEPTH, cycle)] == [encode_key(["b", "4"])]
    ahead = {"seed": [["s"], ["a"]], "step": CHAIN,
             "depth": depths(("s", 0), ("a", 0), ("a", 1), ("b", 1), ("b", 2), ("c", 2), ("c", 3))}
    assert reached(DEPTH, ahead) == []  # c at 3 steps nowhere
    ahead["step"] = CHAIN + [["c", "d"]]
    assert [f["key"] for f in reached(DEPTH, ahead)] == [encode_key(["d", "4"])]


def test_only_a_counter_is_held_to_a_bound():
    """A condition on something else, a step that is no positive constant, or a rule that does not read its own
    relation: no counter, so nothing to hold (the compiler refuses arithmetic in recursion otherwise)."""
    rules = load_rules(DEPTH)
    assert closure.counter(rules["depth_step"], rules) == ("?n", 2)
    assert closure.counter(rules["depth_start"], rules) is None
    other = load_rules(counting({"op": "lt", "left": "?m", "right": "3"}))
    assert closure.counter(other["depth_step"], other) is None
    backwards = counting({"op": "lt", "left": "?n", "right": "3"})
    backwards["rules"][1]["assignments"][0]["right"] = "0"
    backwards = load_rules(backwards)
    assert closure.counter(backwards["depth_step"], backwards) is None
    unstarted = counting({"op": "lt", "left": "?n", "right": "3"})
    unstarted["rules"][0]["head"]["terms"][1] = "?a"
    unstarted = load_rules(unstarted)
    assert closure.counter(unstarted["depth_step"], unstarted) is None  # the other rule does not start ?n


# `depth(a, 0) :- seed(a).  depth(b, m) :- depth(a, n), a < 10, n < 3, b = a + 1, m = n + 1.` Both columns step
# by a constant under an upper bound, but only n starts at a constant in the other rule: n is the counter, and
# a < 10 is a guard of the rule, as the compiler takes it (rules._bound).
TWO = program([relation("seed", "base", "id#"), relation("depth", "derived", "id#", "n#")],
              rule("depth_start", 0, ("depth", "?a", "0"), ("seed", "?a")),
              rule("depth_step", 0, ("depth", "?b", "?m"), ("depth", "?a", "?n"),
                   conditions=[{"op": "lt", "left": "?a", "right": "10"}, {"op": "lt", "left": "?n", "right": "3"}],
                   assignments=[{"var": "?b", "op": "add", "left": "?a", "right": "1"},
                                {"var": "?m", "op": "add", "left": "?n", "right": "1"}]))


def test_the_counter_is_the_column_the_other_rules_start():
    rules = load_rules(TWO)
    assert closure.counter(rules["depth_step"], rules) == ("?n", 2)
    cut = {"seed": [["0"]], "depth": depths(("0", 0), ("1", 1), ("2", 2), ("3", 3))}
    assert [(f["bound"], f["key"]) for f in reached(TWO, cut)] == [("?n <= 2", encode_key(["4", "4"]))]
    proofs = [witness(TWO, "depth_start", a="0")] + [
        witness(TWO, "depth_step", a=str(n), b=str(n + 1), n=str(n), m=str(n + 1)) for n in range(3)]
    assert errors(epoch(TWO, cut, proofs)) == [("bound_reached", "depth", encode_key(["4", "4"]))]


def test_a_guard_on_another_column_is_no_bound():
    """seed(10): the guard a < 10 stops the rule at once, and {(10, 0)} is the whole epoch."""
    whole = {"seed": [["10"]], "depth": depths(("10", 0))}
    assert reached(TWO, whole) == []
    assert epoch(TWO, whole, [witness(TWO, "depth_start", a="10")])["valid"]
