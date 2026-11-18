"""A view and an unrelated native kind keep distinct names in a coverage certificate."""

import json

from rezono_compiler import explain, pack, rules

from test_view_execute import facts, packs, run


def test_compiled_view_preserves_the_role_and_kind_of_a_witnessed_certificate(tmp_path):
    domain, _ = packs(tmp_path)
    (domain / "rules").mkdir()
    (domain / "rules/coverage.dl").write_text(
        '.decl may_read_full(role: symbol, kind: symbol)\n'
        'may_read_full("reader", "span") :- calendar("c").\n', encoding="utf-8")
    program = rules.load(pack.read(domain).rules)
    data = facts([("term-only", None, None)], [])
    data["span"] = [("native",)]
    rows, witnesses = run(program, data)
    assert rows["spans_span"] == {("native",), ("term-only",)}
    assert rows["may_read_full"] == {("reader", "span")}
    [rule] = program.rules_for("may_read_full")
    [binding] = witnesses[rule.id]
    proof = explain.Explainer(program, rows, witnesses).instance(rule, dict(zip(rule.variables, binding)))
    assert json.loads(proof["conclusion"]["key"]) == ["reader", "span"]
    assert [(p["row"]["relation"], json.loads(p["row"]["key"])) for p in proof["premises"]] == [("calendar", ["c"])]
