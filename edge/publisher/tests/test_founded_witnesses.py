"""Planner red tests for publishing every founded witness per conclusion (decisions/publish-founded-witnesses.md, #1445).

Uses the exact hand-written cases of docs/semantics/witness-alternatives-cases.yaml:
- `and-or-two-rules`: both founded witnesses published (chosen first).
- `finite-alternatives-on-a-cycle`: founded witnesses published, cyclic self-loop excluded.
- `role-with-a-hidden-alternative`: strict two-world non-interference — restricted role output in a two-witness
  world (one alternative hidden) is identical to a one-witness world (no hidden alternative), with role-relative
  `load_bearing=True` for the restricted role and `load_bearing=False` for the full role.
"""

import json

import pytest
from rezono_publisher import access

KINDS = {"node", "role"}
COLUMNS = {
    "node": ("node",),
    "role": ("role",),
    "edge": ("node", "node"),
    "reach": ("node", "node"),
    "near": ("node", "node"),
}


def _lit(rel, *terms, stratum=0):
    return {"relation": rel, "terms": list(terms), "polarity": "positive", "stratum": stratum}


def _rel(name, role, arity):
    return {"name": name, "role": role, "key": [{"name": f"c{i}", "type": "string"} for i in range(arity)]}


def _key(*parts):
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


def _witness(rid, head, bindings, premises):
    return {
        "conclusion": {"relation": head[0], "key": _key(*head[1:])},
        "rule_id": rid,
        "bindings": [{"variable": v, "value": x} for v, x in bindings],
        "premises": [
            {"row": {"relation": p[0], "key": _key(*p[1:])}, "polarity": "positive", "stratum": s}
            for p, s in premises
        ],
    }


RULES = {
    "format": "rezono.rules/1",
    "pack": "alternatives",
    "relations": [
        _rel("node", "base", 1),
        _rel("role", "base", 1),
        _rel("may_read", "derived", 3),
        _rel("edge", "base", 2),
        _rel("reach", "derived", 2),
        _rel("near", "derived", 2),
    ],
    "rules": [
        {"id": "near_out", "stratum": 1, "head": {"relation": "near", "terms": ["?a", "?b"]},
         "body": [_lit("edge", "?a", "?b", stratum=0)]},
        {"id": "near_in", "stratum": 1, "head": {"relation": "near", "terms": ["?a", "?b"]},
         "body": [_lit("edge", "?b", "?a", stratum=0)]},
        {"id": "reach_edge", "stratum": 1, "head": {"relation": "reach", "terms": ["?x", "?y"]},
         "body": [_lit("edge", "?x", "?y", stratum=0)]},
        {"id": "reach_step", "stratum": 1, "head": {"relation": "reach", "terms": ["?x", "?z"]},
         "body": [_lit("reach", "?x", "?y", stratum=1), _lit("edge", "?y", "?z", stratum=0)]},
    ],
}


def test_for_role_publishes_all_founded_witnesses_excluding_cyclic():
    # Case 1: and-or-two-rules — near(a,b) has two founded witnesses: near_in(a,b) (chosen) and near_out(a,b).
    # Case 2: finite-alternatives-on-a-cycle — reach(a,a) has founded reach_edge(a,a) & reach_step(a,b,a),
    #         while self-loop reach_step(a,a,a) is cyclic and must be excluded.
    rows = {
        "node": [("a",), ("b",)],
        "role": [("all_reader",)],
        "edge": [("a", "a"), ("a", "b"), ("b", "a")],
        "near": [("a", "b")],
        "reach": [("a", "a"), ("a", "b")],
        "may_read": [("all_reader", "node", "a"), ("all_reader", "node", "b")],
    }
    witnesses = [
        _witness("near_out", ("near", "a", "b"), [("?a", "a"), ("?b", "b")], [(("edge", "a", "b"), 0)]),
        _witness("near_in", ("near", "a", "b"), [("?a", "a"), ("?b", "b")], [(("edge", "b", "a"), 0)]),
        _witness("reach_edge", ("reach", "a", "a"), [("?x", "a"), ("?y", "a")], [(("edge", "a", "a"), 0)]),
        _witness(
            "reach_step",
            ("reach", "a", "a"),
            [("?x", "a"), ("?y", "b"), ("?z", "a")],
            [(("reach", "a", "b"), 1), (("edge", "b", "a"), 0)],
        ),
        # Cyclic self-loop on reach(a,a): must NOT be published.
        _witness(
            "reach_step",
            ("reach", "a", "a"),
            [("?x", "a"), ("?y", "a"), ("?z", "a")],
            [(("reach", "a", "a"), 1), (("edge", "a", "a"), 0)],
        ),
        _witness("reach_edge", ("reach", "a", "b"), [("?x", "a"), ("?y", "b")], [(("edge", "a", "b"), 0)]),
    ]
    _, sees, _ = access.for_role(rows, KINDS, {}, COLUMNS, RULES, witnesses, "all_reader")
    near_ws = [w for w in sees["witnesses"] if w["conclusion"] == {"relation": "near", "key": _key("a", "b")}]
    assert [w["rule_id"] for w in near_ws] == ["near_in", "near_out"]

    reach_aa_ws = [w for w in sees["witnesses"] if w["conclusion"] == {"relation": "reach", "key": _key("a", "a")}]
    assert [
        (w["rule_id"], [b["value"] for b in w["bindings"]]) for w in reach_aa_ws
    ] == [
        ("reach_edge", ["a", "a"]),
        ("reach_step", ["a", "b", "a"]),
    ], "founded alternatives must be published in deterministic order and cyclic reach_step(a,a,a) excluded"


def test_role_with_hidden_alternative_has_zero_count_leak_and_role_relative_load_bearing():
    cols = {**COLUMNS, "edge_in": ("node", None), "edge_out": ("node", None)}
    rules = {
        "format": "rezono.rules/1",
        "pack": "hidden_alt",
        "relations": [
            _rel("node", "base", 1),
            _rel("role", "base", 1),
            _rel("may_read", "derived", 3),
            _rel("edge_in", "base", 2),
            _rel("edge_out", "base", 2),
            _rel("near", "derived", 2),
        ],
        "rules": [
            {"id": "near_in", "stratum": 1, "head": {"relation": "near", "terms": ["?a", "?b"]},
             "body": [_lit("edge_in", "?b", "?a", stratum=0)]},
            {"id": "near_out", "stratum": 1, "head": {"relation": "near", "terms": ["?a", "?b"]},
             "body": [_lit("edge_out", "?a", "?b", stratum=0)]},
        ],
    }
    w_in = _witness("near_in", ("near", "a", "b"), [("?a", "a"), ("?b", "b")], [(("edge_in", "b", "a"), 0)])
    w_out = _witness("near_out", ("near", "a", "b"), [("?a", "a"), ("?b", "b")], [(("edge_out", "a", "b"), 0)])

    # World A: both alternatives exist; restricted_reader reads only node b (so edge_out is hidden).
    rows_two = {
        "node": [("a",), ("b",)],
        "role": [("full_reader",), ("restricted_reader",)],
        "edge_in": [("b", "a")],
        "edge_out": [("a", "b")],
        "near": [("a", "b")],
        "may_read": [
            ("full_reader", "node", "a"),
            ("full_reader", "node", "b"),
            ("restricted_reader", "node", "b"),
        ],
    }
    # World B: only the readable alternative exists (no hidden edge_out at all).
    rows_one = {**rows_two, "edge_out": []}

    _, full_sees, _ = access.for_role(rows_two, KINDS, {}, cols, rules, [w_in, w_out], "full_reader")
    _, restricted_two, _ = access.for_role(rows_two, KINDS, {}, cols, rules, [w_in, w_out], "restricted_reader")
    _, restricted_one, _ = access.for_role(rows_one, KINDS, {}, cols, rules, [w_in], "restricted_reader")

    assert len(full_sees["witnesses"]) == 2
    assert [w["rule_id"] for w in restricted_two["witnesses"]] == ["near_in"]
    # True non-interference: restricted_reader's entire witness set & load_bearing output must be identical
    # whether the hidden alternative exists (World A) or not (World B).
    assert restricted_two == restricted_one

    # Role-relative load_bearing projected from the witness-graph relation:
    assert "load_bearing" in full_sees and "load_bearing" in restricted_two
    assert full_sees["load_bearing"][("near", _key("a", "b"), "edge_in", _key("b", "a"), "positive")] is False
    assert restricted_two["load_bearing"][("near", _key("a", "b"), "edge_in", _key("b", "a"), "positive")] is True
