"""Each declared flow names the decisions that govern it, their standing, whether they were applied, and drift.

Expectation source: decisions/platform-network-policy-provenance.md. The flows are the declared service grants of
the listener case kinds; a decision governs one exact directed source, destination, protocol and port. The
expected rows are written here from the authored records, independently of the policy and matrix inputs.
"""

import copy

import pytest

from case_support import verified

STANDING = "flow_policy_standing"
APPLIED = "flow_policy_applied"
UNAPPLIED = "flow_policy_application_unknown"
DRIFT = "flow_policy_matrix_drift"
ON = "edge"


def decision(key, state="in_force", start=1, end=None, decider=("board",)):
    record = {"id": key, "title": key, "state": state,
              "valid_from": f"2026-04-{start:02}", "valid_from_day": 20260400 + start}
    if decider:
        record["decider"] = list(decider)
    if end is not None:
        record.update(valid_until=f"2026-04-{end:02}", valid_until_day=20260400 + end)
    return record


def tuple_of(key, source, destination, protocol, port, **extra):
    return {"id": key, "source": source, "destination": destination, "protocol": protocol, "port": port, **extra}


def records():
    return {
        "listener_case_zone": [{"id": "apps"}, {"id": "data"}],
        "listener_case_range": [{"id": "apps-range"}],
        "listener_case_source": [{"id": "app", "zone": "apps", "source_range": "apps-range"}],
        "listener_case_destination": [{"id": "db", "zone": "data"}, {"id": "cache", "zone": "data"}],
        # Three declared flows: the same port to two destinations, and another protocol to the same destination.
        "listener_case_listener": [{"id": "db-tcp", "destination": "db", "protocol": "tcp", "port": 5432},
                                   {"id": "cache-tcp", "destination": "cache", "protocol": "tcp", "port": 5432},
                                   {"id": "db-udp", "destination": "db", "protocol": "udp", "port": 5432}],
        "listener_case_service_grant": [{"id": f"grant-{x}", "source": "app", "listener": x}
                                        for x in ("db-tcp", "cache-tcp", "db-udp")],
        "decision": [decision("allow-db"), decision("allow-cache", state="proposed"),
                     decision("allow-udp", end=5), decision("allow-udp-again", decider=()),
                     decision("allow-redis")],
        "reference_date": [{"id": ON, "title": ON, "day": 20260408}],
        "flow_policy_binding": [
            tuple_of("g-db", "app", "db", "tcp", 5432, decision="allow-db"),
            tuple_of("g-cache", "app", "cache", "tcp", 5432, decision="allow-cache"),
            tuple_of("g-udp", "app", "db", "udp", 5432, decision="allow-udp"),
            tuple_of("g-udp-again", "app", "db", "udp", 5432, decision="allow-udp-again"),
            # A decision about a tuple without a declared flow governs nothing.
            tuple_of("g-redis", "app", "cache", "tcp", 6379, decision="allow-redis")],
        # Enforcement readbacks. The cache readback reports another decision's revision.
        "policy_application": [
            tuple_of("seen-db", "app", "db", "tcp", 5432, decision="allow-db", enforcement_point="router-1"),
            tuple_of("seen-cache", "app", "cache", "tcp", 5432, decision="allow-db", enforcement_point="router-1")],
        "policy_matrix_entry": [tuple_of("m-db", "app", "db", "tcp", 5432, revision="matrix-7", verdict="allow")],
    }


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state, tuple(state.derived.get(name) for name in (STANDING, APPLIED, UNAPPLIED, DRIFT))


DB = ("app", "db", "tcp", "5432")
STANDINGS = {(*DB, "allow-db", ON, "in_force"),
             ("app", "cache", "tcp", "5432", "allow-cache", ON, "proposed"),
             ("app", "db", "udp", "5432", "allow-udp", ON, "ended"),
             ("app", "db", "udp", "5432", "allow-udp-again", ON, "decider-missing")}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/platform-network-policy-provenance.md: Derive flow_policy_standing(source, destination, protocol, port, decision, on, standing) with standings "
    "in_force, proposed, ended and decider-missing from std-decision, flow_policy_applied and "
    "flow_policy_application_unknown(source, destination, protocol, port, decision, on), and "
    "flow_policy_matrix_drift(entry, source, destination, protocol, port, decision, on, recorded) in "
    "rules/network_policy_provenance.dl over the declared listener_case_service_grant flows. Declare "
    "FlowPolicyBinding (decision: Decision, source: ListenerCaseSource, destination: ListenerCaseDestination, "
    "protocol, port), PolicyApplication (the same tuple, decision, enforcement_point) and PolicyMatrixEntry (the "
    "same tuple, revision, verdict) in schema/network_policy_provenance.yaml; no fact rows. "
    "Read decisions/platform-network-policy-provenance.md. "
    "Note: Blocked on a kind name clash because platform-core imports std-loop, which already declares "
    "FlowPolicyBinding(run, collector, window, snapshot). Declaring FlowPolicyBinding in "
    "schema/network_policy_provenance.yaml qualifies both engine names to remove flow_policy_binding, breaking "
    "std-loop rules and this test's input and witness expectations."))
def test_network_policy_provenance():
    data = records()
    model, state, (standing, applied, unapplied, drift) = outcome(data)
    assert standing == STANDINGS
    assert (applied, unapplied, drift) == ({(*DB, "allow-db", ON)}, set(), set())
    leaves = verified(APPLIED, (*DB, "allow-db", ON), state=(model, state))
    for relation, key in (("flow_policy_binding__decision", "g-db"), ("policy_application__decision", "seen-db"),
                          ("decision__decider", "allow-db"), ("listener_case_service_grant__listener", "grant-db-tcp")):
        assert any(rel == relation and row[0] == key for rel, row in leaves), relation

    # Without its readback the current decision's application is unknown; its standing stays.
    missing = copy.deepcopy(data)
    missing["policy_application"] = [r for r in missing["policy_application"] if r["id"] != "seen-db"]
    assert outcome(missing)[2] == (STANDINGS, set(), {(*DB, "allow-db", ON)}, set())

    # A changed matrix row is drift with its own entry, and leaves every governing result unchanged.
    changed = copy.deepcopy(data)
    changed["policy_matrix_entry"][0]["verdict"] = "deny"
    model, state, result = outcome(changed)
    row = ("m-db", *DB, "allow-db", ON, "deny")
    assert result == (STANDINGS, {(*DB, "allow-db", ON)}, set(), {row})
    leaves = verified(DRIFT, row, state=(model, state))
    assert any(rel == "policy_matrix_entry__verdict" and key[0] == "m-db" for rel, key in leaves)
    assert any(rel == "flow_policy_binding__decision" and key[0] == "g-db" for rel, key in leaves)
