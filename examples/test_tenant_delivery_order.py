"""Prove that delivery numbers are ordered by admitted submissions in both engines."""

from pathlib import Path
import shutil

import pytest

import feldera
import souffle
from rezono_checker import check
from rezono_checker.rules import load_rules
from rezono_compiler import facts, pack, rules, rules_sql, scenarios
from rules_support import State


PLATFORM = Path(__file__).parent / "platform"
NUMBERS = "tenant_delivery_number"
ORDER = "tenant_delivery_request_order"
PREDECESSOR = "tenant_delivery_predecessor"
SUBMITTED_AT = "tenant_service_request__submitted_at"
FRACTIONAL_REQUESTS = (
    ("elm", "z-before", "2026-01-01T00:00:00.0000000000000000001Z"),
    ("elm", "a-tie", "2026-01-01T00:00:00.0000000000000000002Z"),
    ("elm", "b-tie", "2026-01-01T00:00:00.000000000000000000200+00:00"),
    ("elm", "zero", "2026-01-01T00:00:00.0Z"),
    ("reed", "other", "2025-12-31T23:59:59Z"),
)
FRACTIONAL_NUMBERS = {
    ("elm", "zero", "1"), ("elm", "z-before", "2"), ("elm", "a-tie", "3"),
    ("elm", "b-tie", "4"), ("reed", "other", "1"),
}


@pytest.fixture(scope="module")
def delivery_pack():
    model = pack.read(PLATFORM)
    return model, rules.load(model.rules)


def requests(entries):
    # Reverse both legacy orders, even though callers may still supply them.
    return {"tenant_service_request": [
        {"id": f"{tenant}/{service}", "tenant": tenant, "service": service,
         "profile": "production", "submitted_at": timestamp, "submitted_at_key": len(entries) - index,
         "service_key": len(entries) - index}
        for index, (tenant, service, timestamp) in enumerate(entries)
    ]}


def test_fact_input_ignores_reversed_legacy_order(delivery_pack):
    model, prog = delivery_pack
    records = requests((
        ("elm", "first", "2026-01-01T00:00:00Z"),
        ("elm", "last", "2026-01-02T00:00:00Z"),
    ))
    records["tenant_service_request"][0].update(submitted_at_key=1, service_key=0)
    records["tenant_service_request"][1].update(submitted_at_key=0, service_key=1)
    state = State(model, prog, "m-1", facts.rows_of(model, records))
    assert state.derived[NUMBERS] == {("elm", "first", "1"), ("elm", "last", "2")}


def test_fractional_order_uses_admitted_timestamp_witnesses(delivery_pack):
    model, prog = delivery_pack
    state = State(model, prog, "m-1", facts.rows_of(model, requests(FRACTIONAL_REQUESTS)))
    assert state.derived[NUMBERS] == FRACTIONAL_NUMBERS

    manifest, read = state.manifest()
    checker_rules = load_rules(model.rules)
    for relation in (PREDECESSOR, NUMBERS):
        for key in state.derived[relation]:
            checked = check(state.proof(relation, key), manifest, checker_rules, read)
            assert checked["valid"] and not checked["findings"], checked["findings"]
    proof = state.proof(PREDECESSOR, ("elm", "b-tie", "z-before"))
    submitted = {premise["row"]["key"] for witness in proof["witnesses"]
                 for premise in witness["premises"] if premise["row"]["relation"] == SUBMITTED_AT}
    assert submitted == {
        '["elm/z-before","2026-01-01T00:00:00.0000000000000000001+00:00"]',
        '["elm/b-tie","2026-01-01T00:00:00.0000000000000000002+00:00"]',
    }


@pytest.mark.parametrize("timestamp", [
    "2026-02-29T00:00:00Z",
    "2026-01-01T00:00:00+01:00",
    ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"],
])
def test_fact_input_refuses_invalid_instants(delivery_pack, timestamp):
    model, _ = delivery_pack
    with pytest.raises(facts.LoadError, match=r"tenant_service_request\[1\]\.submitted_at: invalid UTC timestamp"):
        facts.rows_of(model, requests((("elm", "example", timestamp),)))


@pytest.mark.skipif(not shutil.which("souffle"), reason="requires the Souffle executable")
def test_delivery_order_matches_souffle_on_the_written_rules(delivery_pack):
    model, prog = delivery_pack
    rows = scenarios.rule_rows(model, prog, facts.rows_of(model, requests(FRACTIONAL_REQUESTS)))
    source = souffle.pack_source(prog, PLATFORM)
    assert souffle.run(prog, rows, program_text=source)[NUMBERS] == FRACTIONAL_NUMBERS


@pytest.mark.skipif(not feldera.URL, reason="requires FELDERA_URL for the live incremental comparison")
def test_live_delivery_order_matches_batch_after_a_submission_update(delivery_pack):
    model, prog = delivery_pack
    before = facts.rows_of(model, requests(FRACTIONAL_REQUESTS))
    changed = ("elm", "z-before", "2026-01-01T00:00:00.0000000000000000003Z")
    after = facts.rows_of(model, requests((changed, *FRACTIONAL_REQUESTS[1:])))
    changed_numbers = FRACTIONAL_NUMBERS - {("elm", "z-before", "2"), ("elm", "a-tie", "3"), ("elm", "b-tie", "4")}
    changed_numbers |= {("elm", "a-tie", "2"), ("elm", "b-tie", "3"), ("elm", "z-before", "4")}

    relevant = sorted(prog.deps(ORDER))
    original = {table: before[table] for table in relevant}
    drop = {SUBMITTED_AT: sorted(set(before[SUBMITTED_AT]) - set(after[SUBMITTED_AT]))}
    add = {SUBMITTED_AT: sorted(set(after[SUBMITTED_AT]) - set(before[SUBMITTED_AT]))}
    delta = {SUBMITTED_AT: facts.ingress(model, drop, "delete")[SUBMITTED_AT]
             + facts.ingress(model, add)[SUBMITTED_AT]}
    pipeline = "rezono-platform-tenant-delivery"
    feldera.deploy(pipeline, rules_sql.feldera(prog, witnesses=True, relations=(ORDER, PREDECESSOR, NUMBERS)),
                   profile="unoptimized", workers=2)
    try:
        for label, rows, updates, expected in (
            ("m-1", before, facts.ingress(model, original), FRACTIONAL_NUMBERS),
            ("m-2", after, delta, changed_numbers),
        ):
            current = State(model, prog, label, rows)
            feldera.processed(pipeline, feldera.push(pipeline, updates))
            observed = {tuple(str(row[field.name]) for field in prog.relations[NUMBERS].key)
                        for row in feldera.query(pipeline, f'SELECT * FROM "{NUMBERS}"')}
            assert observed == current.derived[NUMBERS] == expected
            for rule in prog.rules_for(PREDECESSOR):
                bindings = {tuple(str(row[column]) for column in rules_sql.witness_columns(rule))
                            for row in feldera.query(pipeline, f'SELECT * FROM "{rule.witness_relation}"')}
                assert bindings == set(current.explainer.witnesses[rule.id])
    finally:
        feldera.stop(pipeline)
        feldera.call("DELETE", f"/v0/pipelines/{pipeline}")
