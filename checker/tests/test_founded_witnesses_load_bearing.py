"""Planner red test for checker verification of premise load_bearing (decisions/publish-founded-witnesses.md, #1445).

Verifies that rezono_checker.proof independently verifies the projected load_bearing flags against the
role's founded witnesses and snapshots, and refuses any forged load_bearing flag with refusal code
`load_bearing_mismatch`.
"""

import json

import pytest
from rezono_checker import proof as checker_proof
from rezono_publisher import proof as pub_proof


def _key(*parts):
    return json.dumps(list(parts), separators=(",", ":"), ensure_ascii=False)


RULES_DOC = {
    "format": "rezono.rules/1",
    "pack": "load_bearing_test",
    "relations": [
        {"name": "edge", "role": "base", "key": [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}]},
        {"name": "anchor", "role": "base", "key": [{"name": "a", "type": "string"}]},
        {
            "name": "near",
            "role": "derived",
            "module": "m",
            "explain": "materialize",
            "key": [{"name": "a", "type": "string"}, {"name": "b", "type": "string"}],
        },
    ],
    "rules": [
        {
            "id": "near_in",
            "module": "m",
            "stratum": "1",
            "head": {"relation": "near", "terms": ["?a", "?b"]},
            "body": [
                {"relation": "anchor", "terms": ["?a"], "polarity": "positive", "stratum": "0"},
                {"relation": "edge", "terms": ["?b", "?a"], "polarity": "positive", "stratum": "0"},
            ],
            "witness": {"relation": "near_in__witness", "variables": ["?a", "?b"]},
            "origin": {"file": "cases.dl", "line": "1"},
        },
        {
            "id": "near_out",
            "module": "m",
            "stratum": "1",
            "head": {"relation": "near", "terms": ["?a", "?b"]},
            "body": [
                {"relation": "anchor", "terms": ["?a"], "polarity": "positive", "stratum": "0"},
                {"relation": "edge", "terms": ["?a", "?b"], "polarity": "positive", "stratum": "0"},
            ],
            "witness": {"relation": "near_out__witness", "variables": ["?a", "?b"]},
            "origin": {"file": "cases.dl", "line": "2"},
        },
    ],
}


def test_checker_verifies_load_bearing_and_refuses_load_bearing_mismatch():
    # anchor(a) appears in BOTH founded witnesses -> load_bearing=True.
    # edge(b,a) and edge(a,b) each appear in only one founded witness -> load_bearing=False.
    witnesses = [
        {
            "conclusion": {"relation": "near", "key": _key("a", "b")},
            "rule_id": "near_in",
            "bindings": [{"variable": "?a", "value": "a"}, {"variable": "?b", "value": "b"}],
            "premises": [
                {"row": {"relation": "anchor", "key": _key("a")}, "polarity": "positive", "stratum": 0},
                {"row": {"relation": "edge", "key": _key("b", "a")}, "polarity": "positive", "stratum": 0},
            ],
        },
        {
            "conclusion": {"relation": "near", "key": _key("a", "b")},
            "rule_id": "near_out",
            "bindings": [{"variable": "?a", "value": "a"}, {"variable": "?b", "value": "b"}],
            "premises": [
                {"row": {"relation": "anchor", "key": _key("a")}, "polarity": "positive", "stratum": 0},
                {"row": {"relation": "edge", "key": _key("a", "b")}, "polarity": "positive", "stratum": 0},
            ],
        },
    ]
    snaps = {
        "anchor": b'[{"key":["a"]}]',
        "edge": b'[{"key":["a","b"]},{"key":["b","a"]}]',
        "near": b'[{"key":["a","b"]}]',
    }
    made, roots = pub_proof.plan(RULES_DOC, {"witnesses": witnesses}, snaps, "v")
    pieces = {k.removeprefix("v/"): b for k, b in made}

    # Forged load_bearing_entries: marks anchor(a) as False when both founded witnesses require it.
    forged_sees = {
        "witnesses": witnesses,
        "load_bearing_entries": [
            {
                "conclusion": {"relation": "near", "key": _key("a", "b")},
                "premise": {"relation": "anchor", "key": _key("a")},
                "how": "positive",
                "load_bearing": False,
            },
            {
                "conclusion": {"relation": "near", "key": _key("a", "b")},
                "premise": {"relation": "edge", "key": _key("a", "b")},
                "how": "positive",
                "load_bearing": False,
            },
            {
                "conclusion": {"relation": "near", "key": _key("a", "b")},
                "premise": {"relation": "edge", "key": _key("b", "a")},
                "how": "positive",
                "load_bearing": False,
            },
        ],
    }
    problems = checker_proof.check_proof(RULES_DOC, forged_sees, snaps, pieces, roots, 65536, 128)
    codes = [getattr(p, "code", str(p)) for p in problems]
    assert "load_bearing_mismatch" in codes, f"expected load_bearing_mismatch refusal, got {codes}"
