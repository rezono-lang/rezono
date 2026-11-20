"""A parameter atom becomes an exact CEL quantifier: decisions/k8s-admission-translator.md, "Atom"."""

import pytest
from rezono_compiler.rules import Atom
from translator_support import evaluate, program, run_cel

TABLE = {
    "list": "params.rows",
    "columns": {"namespace": "object.ns", "service": "{e}.service", "port": "{e}.port"},
    "types": {"namespace": "string", "service": "string", "port": "integer"},
}
PAIRS = {"list": "params.pairs", "columns": {"a": "{e}.a", "b": "{e}.b"}, "types": {"a": "string", "b": "string"}}
TYPES = {"?n": "string", "?s": "string", "?port": "integer", "?x": "string"}
MODEL = [("blue", "web", 443), ("blue", "api", 80), ("green", "web", 443)]


def params_for(namespace):
    return {"rows": [{"service": s, "port": p} for n, s, p in MODEL if n == namespace]}


def test_cel_atom():
    from cel_atom import bind, exists, negative

    request = {"?n": "object.row.namespace", "?s": "object.row.service"}
    conditions, env = bind(Atom("p", ("?n", "?s", "?port")), TABLE, request, TYPES, "e0")
    assert conditions == ["(object.ns == object.row.namespace)", "(e0.service == object.row.service)"]
    assert env == {**request, "?port": "e0.port"}
    assert request == {"?n": "object.row.namespace", "?s": "object.row.service"}
    present = exists(TABLE, "e0", conditions)
    assert present == ("params.rows.exists(e0, (object.ns == object.row.namespace) && "
                       "(e0.service == object.row.service))")
    assert exists(TABLE, "e0", conditions, "(e0.port > 0)") == present[:-1] + " && (e0.port > 0))"

    constants, same = bind(Atom("p", ("?n", "web", "443")), TABLE, request, TYPES, "e0")
    assert constants == ["(object.ns == object.row.namespace)", '(e0.service == "web")', "(e0.port == 443)"]
    assert same == request
    numeric_text, _ = bind(Atom("q", ("443", "?x")), PAIRS, {}, TYPES, "e1")
    assert numeric_text == ['(e1.a == "443")']

    repeated, bound = bind(Atom("q", ("?x", "?x")), PAIRS, {}, TYPES, "e1")
    assert repeated == ["(e1.b == e1.a)"]
    assert bound == {"?x": "e1.a"}
    reflexive = exists(PAIRS, "e1", repeated)
    assert reflexive == "params.pairs.exists(e1, (e1.b == e1.a))"
    assert exists(PAIRS, "e1", []) == "params.pairs.exists(e1, true)"

    full = {**request, "?port": "object.row.port"}
    absent = negative(Atom("p", ("?n", "?s", "?port")), TABLE, full, TYPES, "e0")
    assert absent == ("!params.rows.exists(e0, (object.ns == object.row.namespace) && "
                      "(e0.service == object.row.service) && (e0.port == object.row.port))")
    with pytest.raises(ValueError):
        negative(Atom("p", ("?n", "?s", "?port")), TABLE, request, TYPES, "e0")

    # Rezono's engine and the hand-written answers agree before cel-go is asked.
    pairs = [("blue", "web"), ("blue", "db"), ("green", "web"), ("green", "api"), ("red", "web")]
    joined = program(
        {"p": ("base", [("namespace", "string"), ("service", "string"), ("port", "integer")]),
         "req": ("base", [("namespace", "string"), ("service", "string")]),
         "allow": ("derived", [("namespace", "string"), ("service", "string")])},
        [("allow", ("allow", ["?n", "?s"]), [("req", ["?n", "?s"], "positive"),
                                             ("p", ["?n", "?s", "?port"], "positive")], [])],
    )
    assert evaluate(joined, {"p": MODEL, "req": pairs}, "allow") == {("blue", "web"), ("green", "web")}
    triples = [("blue", "web", 443), ("blue", "web", 80), ("green", "api", 80)]
    unmatched = program(
        {"p": ("base", [("namespace", "string"), ("service", "string"), ("port", "integer")]),
         "req": ("base", [("namespace", "string"), ("service", "string"), ("port", "integer")]),
         "deny": ("derived", [("namespace", "string"), ("service", "string"), ("port", "integer")])},
        [("deny", ("deny", ["?n", "?s", "?port"]), [("req", ["?n", "?s", "?port"], "positive"),
                                                    ("p", ["?n", "?s", "?port"], "negative")], [])],
    )
    assert evaluate(unmatched, {"p": MODEL, "req": triples}, "deny") == {("blue", "web", "80"), ("green", "api", "80")}

    samples = [({"ns": n, "row": {"namespace": n, "service": s}}, params_for(n), present) for n, s in pairs]
    expected = [True, False, True, False, False]
    samples += [({"ns": n, "row": {"namespace": n, "service": s, "port": p}}, params_for(n), absent)
                for n, s, p in triples]
    expected += [False, True, True]
    samples += [({}, {"pairs": [{"a": "x", "b": "x"}, {"a": "x", "b": "y"}]}, reflexive),
                ({}, {"pairs": [{"a": "x", "b": "y"}]}, reflexive)]
    expected += [True, False]
    results = run_cel(samples)
    if results is not None:
        assert results == expected
