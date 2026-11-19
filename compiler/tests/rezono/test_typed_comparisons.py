"""Typed comparisons in native rules lower to the condition the Datalog spelling gives.

decisions/ordered-rule-scalars.md: `utc_instant(a) < utc_instant(b)` and `binary_text(a) < binary_text(b)`
select the comparison type at the comparison. Datalog and native lowering emit the same condition, with
`compare_as`. Expected orders below are authored from the decision's byte and UTC rules, not from an engine.
"""

import importlib

import pytest

from rezono_compiler import batch, pack, rules
from expression_packs import author, compile_rules, register, stage_pack


class TypedComparisonMismatch(AssertionError):
    """A native typed comparison did not lower to one typed condition over the two slot values."""


REQUEST_SCHEMA = """id: https://rezono.example/requests
name: requests
imports:
  - linkml:types
default_range: string
annotations:
  layer: facts
classes:
  Request:
    attributes:
      id:
        identifier: true
      submitted:
        range: string
      tenant:
        range: string
"""

SOURCE = """rezono 0
pack minimal
rule earlier(a: Request, b: Request) when a in Request and b in Request and utc_instant(a.submitted) < utc_instant(b.submitted)
rule tenant_before(a: Request, b: Request) when a in Request and b in Request and binary_text(a.tenant) < binary_text(b.tenant)
"""

ONE_SIDE = """rezono 0
pack minimal
rule earlier(a: Request, b: Request) when a in Request and b in Request and utc_instant(a.submitted) < b.submitted
"""

# r1 ends the leap day, r2 and r3 are the same instant spelled with and without a fraction, and r4 is an
# invalid leap day that orders against nothing. Tenants in UTF-8 byte order: alpha < alpha-next < e + U+0301 < é.
ROWS = {
    "request": [("r1",), ("r2",), ("r3",), ("r4",)],
    "request__submitted": [
        ("r1", "2024-02-29T23:59:59.9Z"), ("r2", "2024-03-01T00:00:00Z"),
        ("r3", "2024-03-01T00:00:00.000Z"), ("r4", "2023-02-29T12:00:00Z"),
    ],
    "request__tenant": [("r1", "alpha"), ("r2", "alpha-next"), ("r3", "é"), ("r4", "é")],
}
EARLIER = [("r1", "r2"), ("r1", "r3")]
TENANT_BEFORE = [("r1", "r2"), ("r1", "r3"), ("r1", "r4"), ("r2", "r3"), ("r2", "r4"), ("r4", "r3")]


def request_pack(tmp_path, source):
    directory = stage_pack(tmp_path)
    (directory / "schema/requests.yaml").write_text(REQUEST_SCHEMA, encoding="utf-8", newline="\n")
    register(directory, author(directory, "order", source))
    return directory


def typed_condition(rule, slot, mode):
    """The one condition of a rule, checked to compare the two values its slot premises bind."""
    values = {terms[0]: terms[1] for item in rule["body"]
              if item["polarity"] == "positive" and item["relation"] == f"request__{slot}"
              for terms in [item["terms"]]}
    if set(values) != {"?a", "?b"} or len(set(values.values())) != 2:
        raise TypedComparisonMismatch(f"{rule['head']['relation']} reads {rule['body']!r}")
    expected = [{"op": "lt", "left": values["?a"], "right": values["?b"], "compare_as": mode}]
    if rule.get("conditions") != expected:
        raise TypedComparisonMismatch(f"{rule['head']['relation']} compares with {rule.get('conditions')!r}")


@pytest.mark.xfail(
    strict=True,
    raises=TypedComparisonMismatch,
    reason="extra: Waits for test_expression_python_scalar_negation (comparisons in native lowering). Then lower "
           "utc_instant(x) and "
           "binary_text(x) on both sides of a comparison in compiler/rezono_compiler/native_rule_lowering.py to one "
           "condition with compare_as over the two slot values, and refuse an annotation on one side only. Read "
           "decisions/ordered-rule-scalars.md.",
)
def test_native_typed_comparisons(tmp_path):
    try:
        program = compile_rules(request_pack(tmp_path / "typed", SOURCE))
    except pack.CompileError as error:
        raise TypedComparisonMismatch(str(error)) from error
    by_head = {rule["head"]["relation"]: rule for rule in program["rules"]}
    typed_condition(by_head["earlier"], "submitted", "utc_instant")
    typed_condition(by_head["tenant_before"], "tenant", "binary_text")

    # Independent evaluation of the lowered program against the authored orders.
    prog = rules.load(program)
    with batch.connect(prog, ROWS) as con:
        batch.compute(con, prog)
        derived = batch.read(con, prog)
    assert sorted(derived["earlier"]) == EARLIER
    assert sorted(derived["tenant_before"]) == TENANT_BEFORE

    # Counter-case: an annotation on one side does not select a comparison type.
    with pytest.raises(pack.CompileError):
        compile_rules(request_pack(tmp_path / "one-side", ONE_SIDE))


DATALOG = """.decl request(id: symbol)
.decl request__submitted(id: symbol, submitted: symbol)
.decl request__tenant(id: symbol, tenant: symbol)
.input request, request__submitted, request__tenant
.decl earlier(a: symbol, b: symbol)
earlier(a, b) :- request(a), request(b), request__submitted(a, s), request__submitted(b, t), utc_instant(s) < utc_instant(t).
.decl tenant_before(a: symbol, b: symbol)
tenant_before(a, b) :- request(a), request(b), request__tenant(a, s), request__tenant(b, t), binary_text(s) < binary_text(t).
.output earlier, tenant_before
"""

CONVERTER_SCHEMA = {
    "request": {"kind": "Request", "columns": {"id": "Request"}, "world": "closed"},
    "request__submitted": {"kind": "Request", "slot": "submitted",
                           "columns": {"id": "Request", "submitted": "Text"}, "world": "closed"},
    "request__tenant": {"kind": "Request", "slot": "tenant",
                        "columns": {"id": "Request", "tenant": "Text"}, "world": "closed"},
}


def comparisons(node):
    if isinstance(node, dict):
        if "cmp" in node:
            yield node
        for value in node.values():
            yield from comparisons(value)
    elif isinstance(node, list):
        for value in node:
            yield from comparisons(value)


@pytest.mark.xfail(
    strict=True,
    raises=TypedComparisonMismatch,
    reason="extra: Keep utc_instant and binary_text on both operands when "
           "compiler/rezono_compiler/native_rule_dl.py plans the native form of a Datalog comparison. Read "
           "decisions/ordered-rule-scalars.md.",
)
def test_converter_keeps_typed_comparisons():
    converter = importlib.import_module("rezono_compiler.native_rule_dl")
    plan = converter.convert_modules([{"pack": "base", "file": "rules/order.dl", "text": DATALOG}],
                                     CONVERTER_SCHEMA, {})
    if plan.get("issues") or not plan["modules"]:
        raise TypedComparisonMismatch(f"the converter refused the typed comparisons: {plan.get('issues')!r}")
    found = {}
    for declaration in plan["modules"][0]["decls"]:
        for node in comparisons(declaration.get("when")):
            left, right = node["cmp"][1:]
            found[declaration["rule"]] = (node["cmp"][0], left.get("call", [None])[0], right.get("call", [None])[0])
    expected = {"earlier": ("<", "utc_instant", "utc_instant"), "tenant_before": ("<", "binary_text", "binary_text")}
    if found != expected:
        raise TypedComparisonMismatch(f"the native plan compares with {found!r}")
