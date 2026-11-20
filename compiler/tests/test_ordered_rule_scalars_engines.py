"""Typed comparisons beyond the rule IR and DuckDB, from decisions/ordered-rule-scalars.md.

Each test covers one translation: the Datalog spelling, the bundle, the gap prefix check, the Soufflé oracle and
Feldera SQL. All of them reuse the hand-authored cases and signs of test_ordered_rule_scalars.py. The expected
rows are those signs, never another engine's result.
"""

import shutil
from contextlib import closing
from uuid import uuid4

import pytest
from rezono_compiler import batch, gap, rules, rules_dl, rules_sql
from test_ordered_rule_scalars import CASES, COMPARISONS, program

COLUMNS = [("mode", "string"), ("case", "string"), ("value", "string")]
OPS = sorted(COMPARISONS[-1] | COMPARISONS[0] | COMPARISONS[1])
SPELLING = {"eq": "=", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}


def inputs():
    left = [(mode, case, a) for mode, case, a, _, _ in CASES if a is not None]
    right = [(mode, case, b) for mode, case, _, b, _ in CASES if b is not None]
    return {"left_value": left, "right_value": right}


def expected():
    return {(mode, case, op) for mode, case, _, _, sign in CASES if sign is not None for op in COMPARISONS[sign]}


def datalog(annotate=lambda mode, side: f"{mode}({side})"):
    lines = [".decl comparison(mode: symbol, case: symbol, operator: symbol)"]
    for mode in ("binary_text", "utc_instant"):
        for op in OPS:
            lines.append(f'comparison("{mode}", c, "{op}") :- left_value("{mode}", c, l), '
                         f'right_value("{mode}", c, r), {annotate(mode, "l")} {SPELLING[op]} {annotate(mode, "r")}.')
    return "\n".join(lines) + "\n"


def evaluated(program_):
    with closing(batch.connect(program_, inputs())) as db:
        batch.compute(db, program_)
        return batch.read(db, program_, ["comparison"])["comparison"]


def test_datalog_spells_typed_comparisons():
    doc = rules_dl.read_program(datalog(), "order", {"left_value": COLUMNS, "right_value": COLUMNS}, "order")
    typed = {(c["op"], c.get("compare_as")) for rule in doc["rules"] for c in rule.get("conditions", ())
             if c["left"].startswith("?") and c["right"].startswith("?")}
    assert typed == {(op, mode) for op in OPS for mode in ("binary_text", "utc_instant")}
    assert evaluated(rules.load(doc)) == expected()

    one_side = datalog(lambda mode, side: f"{mode}({side})" if side == "l" else side)
    with pytest.raises(rules_dl.RuleError):
        rules_dl.read_program(one_side, "order", {"left_value": COLUMNS, "right_value": COLUMNS}, "order")
    outside = ('.decl comparison(mode: symbol, case: symbol, operator: symbol)\n'
               'comparison(m, c, "x") :- left_value(m, c, l), utc_instant(l).\n')
    with pytest.raises(rules_dl.RuleError):
        rules_dl.read_program(outside, "order", {"left_value": COLUMNS}, "order")


def test_the_bundle_keeps_typed_comparisons():
    from rezono_compiler import emit
    prog = rules.load(program())
    ids = {}
    for rule in prog.rules.values():
        head, body = emit.rule_body(prog, rule, None)
        (literal,) = [item for item in body if item["kind"] == "comparison"]
        assert (literal["op"], literal.get("compare_as")) == (rule.conditions[0].op, rule.conditions[0].compare_as)
        ids[rule.id] = emit.rule_id(head, body)
    for op in OPS:
        assert ids[f"binary_text_{op}"] != ids[f"utc_instant_{op}"], op


def test_gap_follows_typed_comparisons():
    prog = rules.load(program())
    rows = {name: [list(row) for row in table] for name, table in inputs().items()}
    want = expected()
    for mode, case, _, _, _ in CASES:
        for op in OPS:
            fails, complete = gap.failures(prog, rows, "comparison", [0, 1, 2], [mode, case, op])
            holds = (mode, case, op) in want
            assert bool(complete) == holds and bool(fails) != holds, (mode, case, op, fails, complete)
        gap.prefix_program(prog, "comparison", [0, 1, 2])


def test_souffle_oracle_orders_typed_values():
    if shutil.which("souffle") is None:
        pytest.skip("needs the pinned souffle")
    from rezono_compiler import rule_proposal_oracle as oracle
    oracle.verified_interpreter()
    assert oracle.evaluate(rules.load(program()), inputs(), "comparison") == expected()


def test_feldera_orders_typed_values():
    import feldera
    sql = rules_sql.feldera(rules.load(program()), witnesses=True)
    assert 'CREATE MATERIALIZED VIEW "comparison"' in sql
    if not feldera.URL:
        return
    pipeline = "rezono-ordered-scalars-" + uuid4().hex
    feldera.deploy(pipeline, sql, profile="unoptimized", workers=2)
    try:
        rows = inputs()
        names = ("mode", "case", "value")
        late = {name: table[len(table) // 2:] for name, table in rows.items()}
        early = {name: table[:len(table) // 2] for name, table in rows.items()}
        for batch_ in (early, late):  # the later half arrives after the first is processed
            feldera.processed(pipeline, feldera.push(pipeline, {
                name: [{"insert": dict(zip(names, row))} for row in table] for name, table in batch_.items()}))
        got = {(r["mode"], r["case"], r["operator"]) for r in feldera.read_relation(pipeline, "comparison")}
        assert got == expected()
    finally:
        feldera.stop(pipeline, delete=True)
