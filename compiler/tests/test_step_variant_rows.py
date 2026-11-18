"""Acceptance for typed speculative rows and witnesses in a safe transition round."""

from contextlib import closing
from copy import deepcopy
from importlib.util import find_spec
from pathlib import Path
from uuid import uuid4

import pytest

import feldera
from rezono_compiler import batch, facts, pack, rules, rules_sql


ROOT = Path(__file__).resolve().parents[2]
NEUTRAL = ROOT / "tests/fixtures/neutral"
OBSERVATIONS = {
    "recorded-readback": (ROOT / "contracts/fixtures/observation/Observation/valid/reconciler.yaml").read_bytes(),
}
RELATION = "outgoing_link"
BEFORE = {("item-a", "link-a"), ("item-a", "link-b"), ("item-d", "link-c")}
AFTER = {("item-a", "link-a"), ("item-b", "link-b"), ("item-c", "link-d")}
# Delete link-c and its incidence, replace link-b's tail, and insert link-d.
DELTA = (
    ("link", ("link-c",), -1),
    ("link__tail", ("link-c", "item-d"), -1),
    ("link__head", ("link-c", "item-a"), -1),
    ("link__tail", ("link-b", "item-a"), -1),
    ("link__tail", ("link-b", "item-b"), 1),
    ("link", ("link-d",), 1),
    ("link__tail", ("link-d", "item-c"), 1),
    ("link__head", ("link-d", "item-a"), 1),
)
FINAL_LINK_ROWS = {
    "link": [("link-a",), ("link-b",), ("link-d",)],
    "link__tail": [("link-a", "item-a"), ("link-b", "item-b"), ("link-d", "item-c")],
    "link__head": [("link-a", "item-b"), ("link-b", "item-c"), ("link-d", "item-a")],
}


def expected_bindings(rule, rows):
    return {tuple({"?i": item, "?l": link}[name] for name in rule.variables) for item, link in rows}


def verify_batch(model, program, rule, rows, expected):
    connection, _, _ = batch.run(model, program, rows)
    with closing(connection):
        result = batch.read(connection, program, [RELATION])[RELATION]
        witnesses = batch.witnesses(connection, program, [rule.id])[rule.id]
    if result != expected or set(witnesses) != expected_bindings(rule, expected):
        pytest.fail("The DuckDB fixture disagrees with the hand-worked rows or witness bindings.")


def verify_incremental(model, program, rule, base):
    name = "rezono-step-variant-" + uuid4().hex
    sql = rules_sql.feldera(program, relations=[RELATION], witnesses=True)
    update = {}
    for relation, row, weight in DELTA:
        operation = "insert" if weight == 1 else "delete"
        update.setdefault(relation, []).extend(facts.ingress(model, {relation: [row]}, operation)[relation])
    feldera.deploy(name, sql, profile="unoptimized", workers=2)
    try:
        for changes, expected in ((facts.ingress(model, base), BEFORE), (update, AFTER)):
            feldera.processed(name, feldera.push(name, changes))
            rows = feldera.query(name, f'SELECT * FROM "{RELATION}"')
            witnesses = feldera.query(name, f'SELECT * FROM "{rule.witness_relation}"')
            actual = {tuple(str(row[column.name]) for column in program.relations[RELATION].key) for row in rows}
            bindings = {tuple(str(row[column]) for column in rules_sql.witness_columns(rule)) for row in witnesses}
            if actual != expected or bindings != expected_bindings(rule, expected):
                pytest.fail("Live Feldera disagrees with the hand-worked fixture and the separate DuckDB result.")
    finally:
        feldera.stop(name)
        feldera.call("DELETE", f"/v0/pipelines/{name}")


@pytest.mark.xfail(strict=True, raises=AssertionError,
                   reason="Implement typed step variants in compiler/rezono_compiler/step_variants.py. "
                          "Read decisions/safe-step-rounds.md. Preserve observation bytes and check exact old rows.")
def test_step_variant_rows():
    model = pack.read(NEUTRAL)
    program = rules.load(model.rules)
    base = facts.load(model, NEUTRAL / "facts/rows.yaml")
    [rule] = program.rules_for(RELATION)
    verify_batch(model, program, rule, base, BEFORE)
    verify_batch(model, program, rule, base | FINAL_LINK_ROWS, AFTER)
    if feldera.URL:
        verify_incremental(model, program, rule, base)

    assert find_spec("rezono_compiler.step_variants"), "the compiler has no typed step-variant evaluator"
    from rezono_compiler.step_variants import evaluate_variant

    original = deepcopy(base)
    observations = OBSERVATIONS.copy()
    result = evaluate_variant(model, program, base, observations, DELTA)
    assert base == original and observations == OBSERVATIONS
    assert result["observations"] == OBSERVATIONS
    assert {relation: set(rows) for relation, rows in result["facts"].items()} == {
        relation: set(rows) for relation, rows in (original | FINAL_LINK_ROWS).items()
    }
    assert set(result["base_rows"][RELATION]) == BEFORE
    assert set(result["variant_rows"][RELATION]) == AFTER
    assert set(result["base_witnesses"][rule.id]) == expected_bindings(rule, BEFORE)
    assert set(result["variant_witnesses"][rule.id]) == expected_bindings(rule, AFTER)

    wrong_old = (*DELTA[:3], ("link__tail", ("link-b", "item-d"), -1), *DELTA[4:])
    with pytest.raises(ValueError):
        evaluate_variant(model, program, base, observations, wrong_old)
    competing = (*DELTA, ("link__tail", ("link-b", "item-b"), -1), ("link__tail", ("link-b", "item-d"), 1))
    with pytest.raises(ValueError):
        evaluate_variant(model, program, base, observations, competing)
    assert base == original and observations == OBSERVATIONS
