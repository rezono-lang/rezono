"""The platform's provides rule retracts the former port and proves the replacement."""

import hashlib
import json
from contextlib import closing
from pathlib import Path
from uuid import uuid4

import pytest

import feldera
from rezono_checker.check import check
from rezono_checker.rules import load_rules
from rezono_compiler import batch, explain, facts, pack, rules, rules_sql

PLATFORM = Path(__file__).parent / "platform"
OLD = ("lb", "ingress", "443")
NEW = ("lb", "ingress", "8443")
UNCHANGED = ("dns", "dns", "53")


def inputs():
    model = pack.read(PLATFORM)
    prog = rules.load(model.rules)
    source = facts.load(model, PLATFORM / "facts/core.yaml")
    # Two independent joins from the public pack. Only one offer changes its port.
    selected = {
        "service__product": [("lb", "loadbalancer"), ("dns", "coredns")],
        "offer__product": [("o-lb", "loadbalancer"), ("o-dns", "coredns")],
        "offer__function": [("o-lb", "ingress"), ("o-dns", "dns")],
        "offer__port": [("o-lb", 443), ("o-dns", 53)],
    }
    for table, rows in selected.items():
        assert set(rows) <= set(source[table]), table
    after = {**selected, "offer__port": [("o-lb", 8443), ("o-dns", 53)]}
    return model, prog, selected, after


def verified(prog, checker_rules, label, inputs, result, witnesses, expected):
    assert result == expected
    rows = {name: [tuple(map(str, row)) for row in values] for name, values in inputs.items()}
    rows["provides"] = result
    explainer = explain.Explainer(prog, rows, witnesses)
    assert {tuple(json.loads(w["conclusion"]["key"])) for w in explainer.chosen()} == expected
    snapshots = {name: explainer.snapshot(name).encode() for name in rows}
    manifest = {"id": label, "snapshots": [
        {"relation": name, "role": "all", "complete": True, "format": "json", "uri": name,
         "sha256": hashlib.sha256(body).hexdigest()} for name, body in snapshots.items()
    ]}
    for key in expected:
        report = check(explainer.proof("provides", key, label), manifest, checker_rules, snapshots.__getitem__)
        assert report["valid"] and not report["findings"], report["findings"]
    return result


def batch_result(model, prog, checker_rules, label, rows, expected):
    rule, = prog.rules_for("provides")
    conn, _, _ = batch.run(model, prog, rows)
    with closing(conn):
        result = batch.read(conn, prog, ["provides"])["provides"]
        witnesses = batch.witnesses(conn, prog, [rule.id])
    return verified(prog, checker_rules, label, rows, result, witnesses, expected)


def test_platform_batch_proves_replacement_and_retains_other_service():
    model, prog, before, after = inputs()
    checker_rules = load_rules(model.rules)
    first = batch_result(model, prog, checker_rules, "m-1", before, {OLD, UNCHANGED})
    second = batch_result(model, prog, checker_rules, "m-2", after, {NEW, UNCHANGED})
    assert (second - first, first - second) == ({NEW}, {OLD})


@pytest.mark.skipif(not feldera.URL, reason="requires FELDERA_URL for the live incremental comparison")
def test_platform_incremental_delta_and_witnesses_match_batch():
    model, prog, before, after = inputs()
    checker_rules = load_rules(model.rules)
    rule, = prog.rules_for("provides")
    pipeline = "rezono-platform-delta-" + uuid4().hex
    sql = rules_sql.feldera(prog, relations=["provides"], witnesses=True)
    update = {"offer__port": [{"delete": {"id": "o-lb", "v": 443}}, {"insert": {"id": "o-lb", "v": 8443}}]}
    feldera.deploy(pipeline, sql, profile="unoptimized", workers=2)
    try:
        observed = []
        for label, rows, changes, expected in [
            ("m-1", before, facts.ingress(model, before), {OLD, UNCHANGED}),
            ("m-2", after, update, {NEW, UNCHANGED}),
        ]:
            feldera.processed(pipeline, feldera.push(pipeline, changes))
            current = {tuple(str(row[c.name]) for c in prog.relations["provides"].key)
                       for row in feldera.query(pipeline, 'SELECT * FROM "provides"')}
            bindings = [tuple(str(row[c]) for c in rules_sql.witness_columns(rule))
                        for row in feldera.query(pipeline, f'SELECT * FROM "{rule.witness_relation}"')]
            observed.append(verified(prog, checker_rules, label, rows, current, {rule.id: bindings}, expected))
            assert current == batch_result(model, prog, checker_rules, label, rows, expected)
        assert (observed[1] - observed[0], observed[0] - observed[1]) == ({NEW}, {OLD})
    finally:
        feldera.stop(pipeline)
        feldera.call("DELETE", f"/v0/pipelines/{pipeline}")
