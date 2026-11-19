"""Platform startup and retirement use observations from the bound cut."""

import pytest

from case_support import ROOT, verified
from management_probes import compiled
from rezono_compiler import pack, rules


def test_startup_transition_cases():
    relation = "startup_transition_result"
    assert relation in rules.load(pack.read(ROOT).rules).derived(), "Missing platform startup transition results"

    run, cut = "startup-case", "current-cut"
    context = {"run": run, "cut": cut}
    records = {
        "safe_round_cut": [{"id": cut, "run": run}],
        "safe_step_request": [
            {"run": run, "id": "expose-entry", "effect": "expose", "subject": "lb"},
            {"run": run, "id": "retire-database", "effect": "retire", "subject": "db-idp"},
        ],
        "service_need": [{"id": "identity-database", "consumer": "idp", "provider": "db-idp", "mode": "run"}],
        "safe_step_observation": [
            {**context, "id": "network-policy", "subject": "lb", "attribute": "network-policy", "value": "effective"},
            {**context, "id": "identity-state", "subject": "idp", "attribute": "runtime", "value": "running"},
            {**context, "id": "database-state", "subject": "db-idp", "attribute": "runtime", "value": "running"},
            {**context, "id": "other-router-allowance", "subject": "another-listener", "attribute": "router-policy",
             "value": "effective"},
        ],
        "safe_step_scope": [
            {**context, "id": "router-inventory", "reader": "router", "scope": "lb"},
            {**context, "id": "consumer-inventory", "reader": "runtime", "scope": "db-idp"},
        ],
    }
    expose = (run, cut, "expose-entry", "blocked", "unprotected-listener", "lb")
    retire = (run, cut, "retire-database", "blocked", "provider-in-use", "idp")
    model, state = compiled(records)
    assert state.derived.get(relation) == {expose, retire}
    assert ("safe_step_scope__scope", ("router-inventory", "lb")) in verified(relation, expose, state=(model, state))
    assert {
        ("service_need__provider", ("identity-database", "db-idp")),
        ("safe_step_observation__value", ("identity-state", "running")),
    } <= verified(relation, retire, state=(model, state))

    unknown = (run, cut, "expose-entry", "unknown", "missing-router-coverage", "lb")
    receipt = records["safe_step_scope"].pop(0)
    _, state = compiled(records)
    assert state.derived.get(relation) == {unknown, retire}
    # A complete receipt from a different cut does not repair the missing coverage.
    records["safe_step_scope"].append({**receipt, "cut": "older-cut"})
    _, state = compiled(records)
    assert state.derived.get(relation) == {unknown, retire}

    records["safe_step_scope"][-1] = receipt
    records["safe_step_observation"].append(
        {**context, "id": "router-allowance", "subject": "lb", "attribute": "router-policy", "value": "effective"})
    records["safe_step_observation"][1]["value"] = "stopped"
    model, state = compiled(records)
    safe_expose = (run, cut, "expose-entry", "safe", "effective-protection", "lb")
    safe_retire = (run, cut, "retire-database", "safe", "consumer-stopped", "idp")
    assert state.derived.get(relation) == {safe_expose, safe_retire}
    assert {
        ("safe_step_observation__value", ("network-policy", "effective")),
        ("safe_step_observation__value", ("router-allowance", "effective")),
    } <= verified(relation, safe_expose, state=(model, state))
    assert ("safe_step_observation__value", ("identity-state", "stopped")) in verified(
        relation, safe_retire, state=(model, state))

    # A stopped consumer without a complete runtime receipt for the provider does not prove absence.
    runtime_receipt = records["safe_step_scope"].pop(0)
    assert runtime_receipt["reader"] == "runtime"
    _, state = compiled(records)
    no_runtime = (run, cut, "retire-database", "unknown", "missing-runtime-coverage", "idp")
    assert state.derived.get(relation) == {safe_expose, no_runtime}
    records["safe_step_scope"].append(runtime_receipt)

    # A contradictory observation in the same cut leaves the protection unknown.
    records["safe_step_observation"].append(
        {**context, "id": "router-denial", "subject": "lb", "attribute": "router-policy", "value": "denied"})
    _, state = compiled(records)
    contradicted = (run, cut, "expose-entry", "unknown", "contradictory-observation", "lb")
    assert state.derived.get(relation) == {contradicted, safe_retire}
    records["safe_step_observation"].pop()

    # Router coverage and allowance without any network-policy read leave the protection unknown.
    policy_read = records["safe_step_observation"].pop(0)
    assert policy_read["attribute"] == "network-policy"
    _, state = compiled(records)
    no_policy = (run, cut, "expose-entry", "unknown", "missing-network-policy-read", "lb")
    assert state.derived.get(relation) == {no_policy, safe_retire}
