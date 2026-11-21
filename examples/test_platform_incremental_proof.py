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
    source = {
        **facts.load(model, PLATFORM / "facts/core.yaml"),
        **facts.load(model, PLATFORM / "facts/port_decision.yaml"),
    }
    # Two independent joins from the public pack: changing PortDecision.port for the load balancer
    # retracts its former provides row and proves the replacement without disturbing dns.
    selected = {
        "service__product": [("lb", "loadbalancer"), ("dns", "coredns")],
        "offer__product": [("o-lb", "loadbalancer"), ("o-dns", "coredns")],
        "offer__function": [("o-lb", "ingress"), ("o-dns", "dns")],
        "port_decision__product": [("pd-lb-ingress", "loadbalancer"), ("pd-dns", "coredns")],
        "port_decision__function": [("pd-lb-ingress", "ingress"), ("pd-dns", "dns")],
        "port_decision__port": [("pd-lb-ingress", 443), ("pd-dns", 53)],
    }
    for table, rows in selected.items():
        assert set(rows) <= set(source[table]), table
    after = {
        **selected,
        "port_decision__port": [("pd-lb-ingress", 8443), ("pd-dns", 53)],
    }
    return model, prog, selected, after


def provides_relations(prog):
    """Derived relations that `provides` depends on, in order, ending with `provides`."""
    derived = set(prog.derived())
    needed, pending = {"provides"}, ["provides"]
    while pending:
        for dep in prog.deps(pending.pop()):
            if dep in derived and dep not in needed:
                needed.add(dep)
                pending.append(dep)
    return [name for name in prog.derived() if name in needed]


def used_base(prog, relations):
    return {dep for name in relations for dep in prog.deps(name)
            if dep in prog.relations and prog.relations[dep].role == "base"}


def proving_witnesses(witnesses, expected):
    proving = {rid: bindings for rid, bindings in witnesses.items() if bindings}
    assert len(proving) == 1, f"expected one provides rule to prove {expected}, got {sorted(proving)}"
    return proving


def verified(prog, checker_rules, label, inputs, result, witnesses, expected):
    assert result == expected
    rows = {name: [tuple(map(str, row)) for row in values]
            for name, values in inputs.items() if name in prog.relations}
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
    provide_rules = prog.rules_for("provides")
    conn, _, _ = batch.run(model, prog, rows)
    with closing(conn):
        result = batch.read(conn, prog, ["provides"])["provides"]
        witnesses = batch.witnesses(conn, prog, [rule.id for rule in provide_rules])
    return verified(prog, checker_rules, label, rows, result, proving_witnesses(witnesses, expected), expected)


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
    relations = provides_relations(prog)
    base = used_base(prog, relations)
    provide_rules = prog.rules_for("provides")
    pipeline = "rezono-platform-delta-" + uuid4().hex
    sql = rules_sql.feldera(prog, relations=relations, witnesses=True)
    before_ingress = facts.ingress(model, {table: rows for table, rows in before.items() if table in base})
    assert "port_decision__port" in base, "port_decision__port does not feed provides"
    update = {
        "port_decision__port": [
            {"delete": {"id": "pd-lb-ingress", "v": 443}},
            {"insert": {"id": "pd-lb-ingress", "v": 8443}},
        ],
    }
    feldera.deploy(pipeline, sql, profile="unoptimized", workers=2)
    try:
        observed = []
        for label, rows, changes, expected in [
            ("m-1", before, before_ingress, {OLD, UNCHANGED}),
            ("m-2", after, update, {NEW, UNCHANGED}),
        ]:
            feldera.processed(pipeline, feldera.push(pipeline, changes))
            current = {tuple(str(row[c.name]) for c in prog.relations["provides"].key)
                       for row in feldera.query(pipeline, 'SELECT * FROM "provides"')}
            witnesses = {
                rule.id: [tuple(str(row[c]) for c in rules_sql.witness_columns(rule))
                          for row in feldera.query(pipeline, f'SELECT * FROM "{rule.witness_relation}"')]
                for rule in provide_rules
            }
            with feldera.comparing():
                observed.append(verified(prog, checker_rules, label, rows, current,
                                         proving_witnesses(witnesses, expected), expected))
                assert current == batch_result(model, prog, checker_rules, label, rows, expected)
        with feldera.comparing():
            assert (observed[1] - observed[0], observed[0] - observed[1]) == ({NEW}, {OLD})
    finally:
        feldera.stop(pipeline, delete=True)
