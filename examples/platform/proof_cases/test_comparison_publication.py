"""Placement against a CMDB export as comparison rows: equal, different or not comparable, with source keys.

Expectation source: decisions/platform-comparison-publication.md. Platform placements come from cluster service
bindings; the export, its observations and its scope are the reference inputs of rules/cmdb_reference.dl. The
expected rows are written here by hand from the authored records. A comparison needs the service in the export's
scope; a one-sided key is not comparable, with the side that is missing.
"""

import copy

import pytest

from case_support import verified

COMPARISON = "placement_comparison"


def records():
    return {
        "cluster_role": [{"id": "worker-role", "control_placement": "local"}],
        "cluster": [{"id": c, "role": "worker-role"} for c in ("east", "west")],
        "cluster_service_binding": [{"id": "b-api", "service": "api", "cluster": "east"},
                                    {"id": "b-queue-east", "service": "queue", "cluster": "east"},
                                    {"id": "b-queue-west", "service": "queue", "cluster": "west"},
                                    {"id": "b-cache", "service": "cache", "cluster": "east"},
                                    {"id": "b-batch", "service": "batch", "cluster": "west"},
                                    {"id": "b-search", "service": "search", "cluster": "east"}],
        "cmdb_export": [{"id": "cmdb-9"}],
        "cmdb_observation": [{"id": "o-api", "export": "cmdb-9", "service": "api", "cluster": "east"},
                             {"id": "o-queue", "export": "cmdb-9", "service": "queue", "cluster": "east"},
                             {"id": "o-legacy", "export": "cmdb-9", "service": "legacy", "cluster": "west"},
                             {"id": "o-search", "export": "cmdb-9", "service": "search", "cluster": "east"}],
        # batch and search lie outside the export's declared scope.
        "cmdb_scope": [{"id": f"scope-{s}", "export": "cmdb-9", "service": s}
                       for s in ("api", "queue", "cache", "legacy")],
    }


EXPECTED = {("cmdb-9", "api", "equal", "same-clusters"),
            ("cmdb-9", "queue", "different", "different-clusters"),
            ("cmdb-9", "cache", "not-comparable", "reference-missing"),
            ("cmdb-9", "legacy", "not-comparable", "platform-missing"),
            ("cmdb-9", "batch", "not-comparable", "scope-incomplete"),
            ("cmdb-9", "search", "not-comparable", "scope-incomplete")}


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state, state.derived.get(COMPARISON)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/platform-comparison-publication.md: Derive placement_comparison(export, service, outcome, reason) in rules/comparison_publication.dl from "
    "cluster_service_placement and the cmdb_reference relations: equal/same-clusters and "
    "different/different-clusters for a scoped service with both sides, not-comparable with reference-missing, "
    "platform-missing or scope-incomplete otherwise. The existing cmdb drift findings stay. Only rules; no new "
    "kinds or fact rows. Read decisions/platform-comparison-publication.md."))
def test_comparison_publication():
    data = records()
    model, state, rows = outcome(data)
    assert rows == EXPECTED
    # The drift findings stay visible beside the comparison.
    assert ("cmdb-9", "cache") in state.derived["cmdb_missing"]
    assert ("cmdb-9", "queue", "west") in state.derived["cmdb_missing_placement"]

    # Each row carries the source keys of both sides and the scope.
    leaves = verified(COMPARISON, ("cmdb-9", "queue", "different", "different-clusters"), state=(model, state))
    for relation, key in (("cmdb_observation__cluster", "o-queue"), ("cluster_service_binding__cluster", "b-queue-west"),
                          ("cmdb_scope__service", "scope-queue")):
        assert any(rel == relation and row[0] == key for rel, row in leaves), relation
    leaves = verified(COMPARISON, ("cmdb-9", "api", "equal", "same-clusters"), state=(model, state))
    for relation, key in (("cmdb_observation__cluster", "o-api"), ("cluster_service_binding__cluster", "b-api")):
        assert any(rel == relation and row[0] == key for rel, row in leaves), relation

    # Reporting the missing cluster makes the sets equal; an extra reported cluster makes them differ again.
    changed = copy.deepcopy(data)
    changed["cmdb_observation"].append({"id": "o-queue-west", "export": "cmdb-9", "service": "queue", "cluster": "west"})
    assert ("cmdb-9", "queue", "equal", "same-clusters") in outcome(changed)[2]
    changed["cmdb_observation"].append({"id": "o-api-west", "export": "cmdb-9", "service": "api", "cluster": "west"})
    swapped = {("cmdb-9", "queue", "different", "different-clusters"), ("cmdb-9", "api", "equal", "same-clusters")}
    assert outcome(changed)[2] == (EXPECTED - swapped) | {
        ("cmdb-9", "queue", "equal", "same-clusters"), ("cmdb-9", "api", "different", "different-clusters")}
