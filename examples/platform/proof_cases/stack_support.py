"""Check real host derivations and re-evaluate a changed stack selection."""

import json

from case_support import ROOT, engine


def assert_host_witness(relation, row, host_relation, host_key):
    _, snapshot = engine()
    proof = snapshot.proof(relation, tuple(row))
    hosts = [json.loads(w["conclusion"]["key"]) for w in proof["witnesses"]
             if w["conclusion"]["relation"] == host_relation]
    assert host_key in hosts, (relation, row, host_relation, host_key)


def rebound(relation, selection, **attributes):
    from rezono_compiler import scenarios
    from rules_support import State, states

    model, program, _ = states(ROOT)
    (label, base), = scenarios.states(model, ROOT)
    edited = dict(base)
    for attribute, replacement in attributes.items():
        table = f"{selection}__{attribute}"
        assert len(base.get(table, ())) == 1, f"Expected one selected value for {table}"
        key, _ = base[table][0]
        edited[table] = [(key, replacement)]
    return State(model, program, label, edited).derived[relation]
