"""The check of a role's proof pieces (rezono_checker.proof): the relation `step` rebuilt from
the rules and the snapshots, and trees that must hold exactly it. Generic: a neutral, hand-made program."""

import copy
import hashlib
import json

import pytest

from rezono_checker.canon import encode_key
from rezono_checker.proof import FORMAT, calc_steps, check_proof, expected, steps


def k(*parts):
    return encode_key(parts)


RULES = {
    "format": "rezono.rules/1",
    "relations": [
        {"name": "e", "role": "base", "key": [{"name": "x", "type": "string"}, {"name": "y", "type": "string"}]},
        {"name": "v", "role": "base", "key": [{"name": "x", "type": "string"}]},
        {"name": "path", "role": "derived", "key": [{"name": "x", "type": "string"}, {"name": "y", "type": "string"}]},
        {"name": "deg", "role": "derived", "key": [{"name": "x", "type": "string"}, {"name": "n", "type": "integer"}]},
        {"name": "lone", "role": "derived", "key": [{"name": "x", "type": "string"}]},
    ],
    "rules": [
        {"id": "path", "stratum": "0", "head": {"relation": "path", "terms": ["?x", "?y"]},
         "body": [{"relation": "e", "terms": ["?x", "?y"], "polarity": "positive", "stratum": "0"}]},
        {"id": "deg", "stratum": "1", "head": {"relation": "deg", "terms": ["?x", "?n"]},
         "body": [{"relation": "v", "terms": ["?x"], "polarity": "positive", "stratum": "0"}],
         "aggregates": [{"relation": "e", "terms": ["?x", "_"], "function": "count", "as": "?n", "stratum": "0"}]},
        {"id": "lone", "stratum": "1", "head": {"relation": "lone", "terms": ["?x"]},
         "body": [{"relation": "v", "terms": ["?x"], "polarity": "positive", "stratum": "0"},
                  {"relation": "path", "terms": ["?x", "?x"], "polarity": "negative", "stratum": "0"}]},
    ],
}


def witness(relation, key, rule, bindings, premises, aggregates=()):
    w = {"conclusion": {"relation": relation, "key": key}, "rule_id": rule,
         "bindings": [{"variable": v, "value": x} for v, x in bindings],
         "premises": [{"row": {"relation": r, "key": pk}, "polarity": pol, "stratum": 0} for r, pk, pol in premises]}
    if aggregates:
        w["aggregates"] = list(aggregates)
    return w


WITNESSES = [
    witness("deg", k("a", "1"), "deg", [("?x", "a"), ("?n", "1")], [("v", k("a"), "positive")],
            [{"relation": "e", "position": 0, "group_key": k("a"), "count": 1, "contributors_sha256": "-", "result": "known:1"}]),
    witness("lone", k("a"), "lone", [("?x", "a")], [("v", k("a"), "positive"), ("path", k("a", "a"), "negative")]),
    witness("path", k("a", "b"), "path", [("?x", "a"), ("?y", "b")], [("e", k("a", "b"), "positive")]),
]


def snapshot(*keys):
    return ("[\n" + ",\n".join(json.dumps({"key": list(p)}, separators=(",", ":")) for p in keys) + "\n]\n").encode()


SNAPSHOTS = {"e": snapshot(("a", "b"), ("b", "c")), "v": snapshot(("a",), ("b",)), "path": snapshot(("a", "b")),
             "deg": snapshot(("a", "1")), "lone": snapshot(("a",))}


def rows():
    from rezono_checker.snapshots import read_rows
    return {rel: read_rows(b, "json") for rel, b in SNAPSHOTS.items()}


def test_step_is_rebuilt_from_the_rules_and_the_snapshots():
    assert steps(RULES, WITNESSES, rows()) == {
        ("deg", k("a", "1"), "v", k("a"), "positive", 0),
        ("deg", k("a", "1"), "e", k("a", "b"), "contributes", 0),  # the group of x = a, not e(b, c)
        ("lone", k("a"), "v", k("a"), "positive", 0),
        ("lone", k("a"), "path", k("a", "a"), "negative", 1),
        ("path", k("a", "b"), "e", k("a", "b"), "positive", 0),
    }


def sha(b):
    return hashlib.sha256(b).hexdigest()


def leaves(want):
    """Every tree as one leaf, its own root: the smallest valid shape."""
    pieces, roots = {}, {}
    for t, by in want.items():
        roots[t] = {}
        for rel, rs in by.items():
            data = json.dumps({"format": FORMAT, "tree": t, "relation": rel, "level": 0, "rows": rs},
                              sort_keys=True, separators=(",", ":")).encode()
            path = f"proof/{t}/{rel}/0/0.json"
            pieces[path], roots[t][rel] = data, {"file": path, "sha256": sha(data), "levels": 1}
    return pieces, roots


def _lb_entries(witnesses):
    seen = {}
    for w in witnesses:
        c = w["conclusion"]
        for p in w.get("premises", ()):
            key = (c["relation"], c["key"], p["row"]["relation"], p["row"]["key"], p["polarity"])
            seen[key] = True
    return [
        {"conclusion": {"relation": cr, "key": ck}, "premise": {"relation": pr, "key": pk},
         "how": how, "load_bearing": flag}
        for (cr, ck, pr, pk, how), flag in sorted(seen.items())
    ]


def check(pieces, roots, witnesses=WITNESSES, limit=65536, fanout=128):
    return check_proof(RULES, {"witnesses": witnesses, "load_bearing_entries": _lb_entries(witnesses)},
                       SNAPSHOTS, pieces, roots, limit, fanout)


def test_missing_load_bearing_entries_is_refused():
    pieces, roots = leaves(expected(WITNESSES, steps(RULES, WITNESSES, rows())))
    problems = check_proof(RULES, {"witnesses": WITNESSES}, SNAPSHOTS, pieces, roots, 65536, 128)
    assert any(getattr(p, "code", None) == "load_bearing_mismatch" for p in problems), problems


def test_the_exact_trees_pass():
    pieces, roots = leaves(expected(WITNESSES, steps(RULES, WITNESSES, rows())))
    assert check(pieces, roots) == []
    assert sorted(roots["forward"]) == ["e", "path", "v"]  # a negative premise's absent row is a node too


def test_a_two_level_tree_passes_and_wrong_bounds_are_found():
    want = expected(WITNESSES, steps(RULES, WITNESSES, rows()))
    pieces, roots = leaves(want)
    rs = want["forward"]["v"]
    halves = []
    for n, part in enumerate((rs[:1], rs[1:])):
        data = json.dumps({"format": FORMAT, "tree": "forward", "relation": "v", "level": 0, "rows": part},
                          sort_keys=True, separators=(",", ":")).encode()
        pieces[f"proof/forward/v/0/{n}.json"] = data
        halves.append({"first": part[0], "last": part[-1], "file": f"proof/forward/v/0/{n}.json", "sha256": sha(data)})
    page = json.dumps({"format": FORMAT, "tree": "forward", "relation": "v", "level": 1, "children": halves},
                      sort_keys=True, separators=(",", ":")).encode()
    pieces["proof/forward/v/1/0.json"] = page
    roots["forward"]["v"] = {"file": "proof/forward/v/1/0.json", "sha256": sha(page), "levels": 2}
    assert check(pieces, roots) == []
    bad = copy.deepcopy(halves)
    bad[0]["last"] = bad[1]["last"]
    page = json.dumps({"format": FORMAT, "tree": "forward", "relation": "v", "level": 1, "children": bad},
                      sort_keys=True, separators=(",", ":")).encode()
    pieces["proof/forward/v/1/0.json"] = page
    roots["forward"]["v"]["sha256"] = sha(page)
    assert any("bounds" in p for p in check(pieces, roots))
    assert any("children" in p for p in check(pieces, roots, fanout=1))


def test_a_missing_edge_a_changed_piece_an_extra_piece_and_a_piece_too_large_are_found():
    want = expected(WITNESSES, steps(RULES, WITNESSES, rows()))
    fewer = copy.deepcopy(want)
    fewer["back"]["deg"].pop()  # e.g. a contributor left out
    assert any("not the role's proof graph" in p for p in check(*leaves(fewer)))
    pieces, roots = leaves(want)
    pieces["proof/back/path/0/0.json"] += b" "
    assert any("not the piece its parent names" in p for p in check(pieces, roots))
    pieces, roots = leaves(want)
    pieces["proof/back/other/0/0.json"] = b"{}"
    assert any("no tree reaches" in p for p in check(pieces, roots))
    assert any("more than" in p for p in check(*leaves(want), limit=100))
    del roots["witness"]["lone"]
    assert any("witness/lone: no tree" in p for p in check(pieces, roots))


def test_premise_positions_come_from_the_rule_not_from_the_witness():
    """A witness whose premises are listed in another order still gives the rule's positions."""
    turned = copy.deepcopy(WITNESSES)
    turned[1]["premises"].reverse()
    assert steps(RULES, turned, rows()) == steps(RULES, WITNESSES, rows())


def test_a_piece_carries_exactly_its_contract():
    """No extra field can hide data in a checked piece: leaves, pages, child references and roots alike."""
    want = expected(WITNESSES, steps(RULES, WITNESSES, rows()))

    def changed(path, change):
        pieces, roots = leaves(want)
        piece = json.loads(pieces[path])
        change(piece)
        pieces[path] = json.dumps(piece, sort_keys=True, separators=(",", ":")).encode()
        t, rel = path.split("/")[1:3]
        roots[t][rel]["sha256"] = sha(pieces[path])
        return check(pieces, roots)

    assert any("fields" in p for p in changed("proof/back/path/0/0.json",
                                                lambda p: p.update(secret_rows=[{"key": ["hidden-record"]}])))
    assert any("not level" in p for p in changed("proof/back/path/0/0.json", lambda p: p.update(level=False)))
    assert any("rows is not a list" in p for p in changed("proof/back/path/0/0.json", lambda p: p.update(rows={})))
    pieces, roots = leaves(want)
    roots["back"]["path"]["extra"] = 1
    assert any("the root is not exactly" in p for p in check(pieces, roots))
    # a page whose child reference carries more than first, last, file and sha256
    rs = want["forward"]["v"]
    leaf = json.dumps({"format": FORMAT, "tree": "forward", "relation": "v", "level": 0, "rows": rs},
                      sort_keys=True, separators=(",", ":")).encode()
    child = {"first": rs[0], "last": rs[-1], "file": "proof/forward/v/0/0.json", "sha256": sha(leaf), "note": "x"}
    page = json.dumps({"format": FORMAT, "tree": "forward", "relation": "v", "level": 1, "children": [child]},
                      sort_keys=True, separators=(",", ":")).encode()
    pieces, roots = leaves(want)
    pieces["proof/forward/v/0/0.json"], pieces["proof/forward/v/1/0.json"] = leaf, page
    roots["forward"]["v"] = {"file": "proof/forward/v/1/0.json", "sha256": sha(page), "levels": 2}
    assert any("a child is not exactly" in p for p in check(pieces, roots))


# Calculation witnesses: a calculation over a rule's row, one over that calculation, one without premises.
CALC = [
    {"conclusion": {"relation": "c__deg", "key": k("a", "1", "known", "")}, "rule": "c_deg", "state": "known",
     "premises": [{"relation": "deg", "key": k("a", "1")}], "reads": ["deg"], "steps": []},
    {"conclusion": {"relation": "c__twice", "key": k("a", "2", "known", "")}, "rule": "c_twice", "state": "known",
     "premises": [{"relation": "c__deg", "key": k("a", "1", "known", "")}, {"relation": "deg", "key": k("a", "1")}],
     "reads": ["deg"], "steps": []},
    {"conclusion": {"relation": "c__zero", "key": k("a", "0", "known", "")}, "rule": "c_zero", "state": "known",
     "reads": [], "steps": []},
]


def test_calculation_steps_are_each_premise_at_its_index():
    assert calc_steps(CALC) == {
        ("c__deg", k("a", "1", "known", ""), "deg", k("a", "1"), "positive", 0),
        ("c__twice", k("a", "2", "known", ""), "c__deg", k("a", "1", "known", ""), "positive", 0),
        ("c__twice", k("a", "2", "known", ""), "deg", k("a", "1"), "positive", 1),
    }


def test_trees_with_calculations_pass_and_a_missing_calculation_is_found():
    """The witness tree holds both kinds, unchanged; a calculation without premises is a witness only."""
    want = expected(WITNESSES + CALC, steps(RULES, WITNESSES, rows()) | calc_steps(CALC))
    pieces, roots = leaves(want)
    sees = {"witnesses": WITNESSES, "calc_witnesses": CALC, "load_bearing_entries": _lb_entries(WITNESSES)}
    assert check_proof(RULES, sees, SNAPSHOTS, pieces, roots, 65536, 128) == []
    assert "c__zero" in roots["witness"] and "c__zero" not in roots["back"]
    # Without the calculation witnesses the same trees are not the role's graph: trees for nothing.
    assert any("a tree for nothing" in p for p in check(pieces, roots))
    # Calculations only, no rules at all.
    only = expected(CALC[2:], calc_steps(CALC[2:]))
    assert check_proof({"rules": []}, {"witnesses": [], "calc_witnesses": CALC[2:]}, SNAPSHOTS, *leaves(only), 65536, 128) == []


# A sum over a key column, a min over a value column (with an unknown cell) and a count, each per x.
WEIGHED = {
    "format": "rezono.rules/1",
    "relations": [
        {"name": "v", "role": "base", "key": [{"name": "x", "type": "string"}]},
        {"name": "w", "role": "base", "key": [{"name": "x", "type": "string"}, {"name": "y", "type": "string"},
                                              {"name": "n", "type": "integer"}]},
        {"name": "m", "role": "base", "key": [{"name": "x", "type": "string"}, {"name": "y", "type": "string"}],
         "values": [{"name": "amount", "type": "integer"}]},
        {"name": "load", "role": "derived", "key": [{"name": "x", "type": "string"}, {"name": "n", "type": "integer"}]},
        {"name": "least", "role": "derived", "key": [{"name": "x", "type": "string"}, {"name": "n", "type": "integer"}]},
        {"name": "deg", "role": "derived", "key": [{"name": "x", "type": "string"}, {"name": "n", "type": "integer"}]},
    ],
    "rules": [
        {"id": name, "stratum": "1", "head": {"relation": name, "terms": ["?x", "?n"]},
         "body": [{"relation": "v", "terms": ["?x"], "polarity": "positive", "stratum": "0"}],
         "aggregates": [{"relation": rel, "terms": terms, "function": fn, "as": "?n", "stratum": "0"}
                        | ({"over": over} if over else {})]}
        for name, rel, terms, fn, over in (("load", "w", ["?x", "_", "_"], "sum", "n"),
                                           ("least", "m", ["?x", "_"], "min", "amount"),
                                           ("deg", "w", ["?x", "_", "_"], "count", None))
    ],
}
WEIGHED_SNAPSHOTS = {
    "v": snapshot(("a",)),
    "w": snapshot(("a", "p", "3"), ("a", "q", "-4"), ("b", "p", "5")),
    "m": json.dumps([{"key": ["a", "p"], "values": {"amount": {"state": "known", "value": "7"}}},
                     {"key": ["a", "q"], "values": {"amount": {"state": "unknown"}}}]).encode(),
    "load": snapshot(("a", "-1")), "least": snapshot(("a", "7")), "deg": snapshot(("a", "2")),
}
WEIGHED_WITNESSES = [
    witness(name, k("a", n), name, [("?x", "a"), ("?n", n)], [("v", k("a"), "positive")],
            [{"relation": rel, "position": 0, "group_key": k("a"), "count": 2, "contributors_sha256": "-", "result": "-"}])
    for name, n, rel in (("deg", "2", "w"), ("least", "7", "m"), ("load", "-1", "w"))
]


def weighed_rows():
    from rezono_checker.snapshots import read_rows
    return {rel: read_rows(b, "json") for rel, b in WEIGHED_SNAPSHOTS.items()}


def weighed_check(want):
    pieces, roots = leaves(want)
    return check_proof(WEIGHED, {"witnesses": WEIGHED_WITNESSES, "load_bearing_entries": _lb_entries(WEIGHED_WITNESSES)},
                       WEIGHED_SNAPSHOTS, pieces, roots, 65536, 128)


def test_a_contributes_edge_of_a_sum_or_a_min_carries_the_cell_the_aggregate_reads():
    """The value is read from the role's snapshot as the proof check reads it: a key column the aggregate
    ranges over, or a value column with its state. A count edge and a premise carry none."""
    got = steps(WEIGHED, WEIGHED_WITNESSES, weighed_rows())
    assert {s for s in got if s[4] == "contributes"} == {
        ("deg", k("a", "2"), "w", k("a", "p", "3"), "contributes", 0),
        ("deg", k("a", "2"), "w", k("a", "q", "-4"), "contributes", 0),
        ("least", k("a", "7"), "m", k("a", "p"), "contributes", 0, "known:7"),
        ("least", k("a", "7"), "m", k("a", "q"), "contributes", 0, "unknown"),  # unknown is said, never left out
        ("load", k("a", "-1"), "w", k("a", "p", "3"), "contributes", 0, "known:3"),
        ("load", k("a", "-1"), "w", k("a", "q", "-4"), "contributes", 0, "known:-4"),
    }
    assert all(len(s) == 6 for s in got if s[4] != "contributes")
    want = expected(WEIGHED_WITNESSES, got)
    assert [k("a", "-1"), "contributes", 0, "w", k("a", "p", "3"), "known:3"] in want["back"]["load"]
    assert [k("a", "p", "3"), "load", k("a", "-1"), "contributes", 0, "known:3"] in want["forward"]["w"]
    assert weighed_check(want) == []


def test_the_valued_edges_of_an_aggregate_are_the_contributors_the_proof_check_hashes():
    """The checker recounts the aggregate from exactly the rows the edges name: per aggregate, the sorted
    [key, value] of its edges is the list `recompute` hashes, as many as it counts, and they fold to its result."""
    from rezono_checker.canon import sha256_json
    from rezono_checker.check import recompute
    from rezono_checker.rules import load_rules

    rules, rs = load_rules(WEIGHED), weighed_rows()
    got = steps(WEIGHED, WEIGHED_WITNESSES, rs)
    for name, result in (("load", "known:-1"), ("least", "unknown"), ("deg", "known:2")):
        spec = rules[name].aggregates[0]
        edges = sorted([p_key, *value] for c_rel, _, _, p_key, how, _, *value in got if (c_rel, how) == (name, "contributes"))
        count, contributors, folded, _ = recompute(spec, [(0, "a")], rs[spec.atom.relation])
        assert (len(edges), sha256_json(edges), folded) == (count, contributors, result)


@pytest.mark.parametrize("tree,relation", [("back", "load"), ("forward", "w")])
def test_a_changed_a_missing_and_an_added_contribution_are_found(tree, relation):
    """The planted fault: one contribution changed, in either order of the graph; also one left out
    (the edge without its value), one on a count edge and one on a premise."""
    want = expected(WEIGHED_WITNESSES, steps(WEIGHED, WEIGHED_WITNESSES, weighed_rows()))
    at = next(i for i, r in enumerate(want[tree][relation]) if r[-1] == "known:3")

    def planted(change):
        bad = copy.deepcopy(want)
        change(bad[tree][relation], at)
        bad[tree][relation].sort()
        return weighed_check(bad)

    for change in (lambda rs, i: rs[i].__setitem__(-1, "known:2"),  # 3 became 2: the steps no longer add up
                   lambda rs, i: rs[i].pop(),  # the contribution left out
                   lambda rs, i: rs[i].__setitem__(-1, "unknown")):  # a known cell passed off as unknown
        assert planted(change) == [f"{tree}/{relation}: the rows are not the role's proof graph"]
    count = "deg" if tree == "back" else "w"
    bad = copy.deepcopy(want)
    next(r for r in bad[tree][count] if "contributes" in r and len(r) == 5).append("known:1")  # a count reads no cell
    assert weighed_check(bad) == [f"{tree}/{count}: the rows are not the role's proof graph"]
    premise = "load" if tree == "back" else "v"
    bad = copy.deepcopy(want)
    next(r for r in bad[tree][premise] if "positive" in r).append("known:1")
    assert weighed_check(bad) == [f"{tree}/{premise}: the rows are not the role's proof graph"]
