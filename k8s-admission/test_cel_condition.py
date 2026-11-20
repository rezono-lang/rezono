"""A rule comparison becomes exact CEL: decisions/k8s-admission-translator.md, "Condition"."""

import operator

import pytest
from rezono_compiler.rules import Condition
from translator_support import evaluate, program, run_cel

OPS = {"eq": operator.eq, "ne": operator.ne, "lt": operator.lt,
       "le": operator.le, "gt": operator.gt, "ge": operator.ge}
VALUES = (-3, 0, 7)


def test_cel_condition():
    from cel_condition import condition

    text = {"?service": "string", "?port": "integer", "?a": "integer", "?b": "integer"}
    env = {"?service": "r.service", "?port": "r.port", "?a": "r.a", "?b": "r.b"}
    exact = [
        (Condition("eq", "?service", "web"), '(r.service == "web")'),
        (Condition("eq", "?service", "443"), '(r.service == "443")'),
        (Condition("le", "?port", "1024"), "(r.port <= 1024)"),
        (Condition("ne", "?a", "?b"), "(r.a != r.b)"),
        (Condition("gt", "-5", "?a"), "(-5 > r.a)"),
        (Condition("lt", "?a", "?b"), "(r.a < r.b)"),
        (Condition("ge", "?a", "0"), "(r.a >= 0)"),
        (Condition("eq", "1", "1"), "(1 == 1)"),
        (Condition("eq", "web", "web"), '("web" == "web")'),
    ]
    for cond, expected in exact:
        assert condition(cond, env, text) == expected, cond
    with pytest.raises(ValueError):
        condition(Condition("eq", "?missing", "web"), env, {**text, "?missing": "string"})
    with pytest.raises(ValueError):
        condition(Condition("like", "?service", "web"), env, text)

    # Rezono's own engine and plain Python give the same answer as the hand-written truth table.
    pairs = [(a, b) for a in VALUES for b in VALUES]
    samples, expected = [], []
    for op, function in OPS.items():
        prog = program(
            {"pair": ("base", [("a", "integer"), ("b", "integer")]),
             "kept": ("derived", [("a", "integer"), ("b", "integer")])},
            [("kept", ("kept", ["?a", "?b"]), [("pair", ["?a", "?b"], "positive")], [(op, "?a", "?b")])],
        )
        kept = evaluate(prog, {"pair": pairs}, "kept")
        assert kept == {(str(a), str(b)) for a, b in pairs if function(a, b)}, op
        expression = condition(Condition(op, "?a", "?b"), {"?a": "object.a", "?b": "object.b"}, text)
        for a, b in pairs:
            samples.append(({"a": a, "b": b}, {}, expression))
            expected.append(function(a, b))
    for op in ("eq", "ne"):
        expression = condition(Condition(op, "?service", "web"), {"?service": "object.s"}, text)
        for service in ("web", "api", ""):
            samples.append(({"s": service}, {}, expression))
            expected.append(OPS[op](service, "web"))
    results = run_cel(samples)
    if results is not None:
        assert results == expected
