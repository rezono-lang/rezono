"""Function dependency gaps: a missing solution, a missing placement, and a function a cluster loss leaves unserved.

Expectation source: decisions/platform-dependency-gaps.md. The expected rows are written here from the authored
records below, never read from the engine. A cluster loss is an ordinary what-if: the hypothetical state adds one
withdrawal record and keeps every other record.
"""

import copy

import pytest

from case_support import verified

GAP = "dependency_gap"
UNKNOWN = "dependency_gap_unknown"
NO = "no"


def records():
    from management_probes import _committed

    has_offer_port = "port" in _committed().kinds["offer"].slots
    function = lambda key: {"id": key, "recovery_allowed": NO, "open_by_design": NO}
    service = lambda key, product: {"id": key, "product": product, "role": "app-role", "step": 1}
    offer = lambda key, product, fn, port: {
        "id": key, "product": product, "function": fn, **({"port": port} if has_offer_port else {}),
    }
    return {
        "zone": [{"id": "inner", "outside": NO, "entry_boundary": NO, "isolated_recovery": NO, "workload": "yes"}],
        "cluster_class": [{"id": "shared"}],
        "platform_role": [{"id": "app-role", "zone": "inner", "cluster_class": "shared", "runs_images": "yes",
                           "build_authority": NO}],
        "function": [function("login"), function("queue"), function("search"), function("metrics")],
        "product": [{"id": "shop-app"}, {"id": "idp-app"}, {"id": "queue-app"}, {"id": "metrics-app"}],
        "offer": [offer("o-login", "idp-app", "login", 443),
                  offer("o-queue", "queue-app", "queue", 5672),
                  offer("o-metrics", "metrics-app", "metrics", 9090)],
        "demand": [{"id": "d-login", "product": "shop-app", "function": "login"},
                   {"id": "d-queue", "product": "shop-app", "function": "queue"},
                   {"id": "d-search", "product": "shop-app", "function": "search"}],
        "service": [service("shop", "shop-app"), service("idp", "idp-app"), service("mq", "queue-app"),
                    service("metrics", "metrics-app")],
        "cluster_role": [{"id": "worker-role", "control_placement": "local"}],
        "cluster": [{"id": c, "role": "worker-role"} for c in ("east", "west", "north")],
        # The queue provider has no placement at all.
        "cluster_service_binding": [{"id": "b-shop", "service": "shop", "cluster": "east"},
                                    {"id": "b-idp-east", "service": "idp", "cluster": "east"},
                                    {"id": "b-idp-alt", "service": "idp", "cluster": "west"},
                                    {"id": "b-metrics", "service": "metrics", "cluster": "west"}],
        # Topology assertions: north shares a failure domain with east.
        "failure_domain_membership": [{"id": "m-east", "cluster": "east", "domain": "room-a"},
                                      {"id": "m-west", "cluster": "west", "domain": "room-b"},
                                      {"id": "m-north", "cluster": "north", "domain": "room-a"}],
        # Each receipt says the providers and placements of that function were completely inventoried.
        "function_inventory_receipt": [{"id": f"r-{f}", "function": f} for f in ("login", "queue", "search")],
    }


def without(data, kind, key):
    changed = copy.deepcopy(data)
    changed[kind] = [r for r in changed[kind] if r["id"] != key]
    return changed


def lose(data, cluster):
    changed = copy.deepcopy(data)
    changed["cluster_withdrawal"] = [{"id": "loss", "cluster": cluster}]
    return changed


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state, state.derived.get(GAP), state.derived.get(UNKNOWN)


def leaf(leaves, relation, key):
    return any(rel == relation and row[0] == key for rel, row in leaves)


def test_dependency_gaps():
    data = records()
    base_gaps = {("shop", "queue", "no-placement"), ("shop", "search", "no-solution")}

    model, state, gaps, unknown = outcome(data)
    assert (gaps, unknown) == (base_gaps, set())
    leaves = verified(GAP, ("shop", "queue", "no-placement"), state=(model, state))
    assert leaf(leaves, "function_inventory_receipt__function", "r-queue")
    assert leaf(leaves, "demand__function", "d-queue")

    # Without its receipt a missing placement or solution is unknown, not a gap.
    _, _, gaps, unknown = outcome(without(data, "function_inventory_receipt", "r-queue"))
    assert (gaps, unknown) == ({("shop", "search", "no-solution")}, {("shop", "queue", "coverage-missing")})

    # Losing east leaves login served from west in another failure domain: the what-if adds nothing.
    _, _, gaps, unknown = outcome(lose(data, "east"))
    assert (gaps, unknown) == (base_gaps, set())

    # The alternate moved to north shares east's failure domain; metrics on west serves another function.
    moved = copy.deepcopy(data)
    next(b for b in moved["cluster_service_binding"] if b["id"] == "b-idp-alt")["cluster"] = "north"
    assert outcome(moved)[2:] == (base_gaps, set())
    model, state, gaps, unknown = outcome(lose(moved, "east"))
    hard = ("shop", "login", "no-independent-placement")
    assert gaps - base_gaps == {hard} and base_gaps <= gaps and unknown == set()
    leaves = verified(GAP, hard, state=(model, state))
    assert leaf(leaves, "cluster_withdrawal__cluster", "loss")
    assert leaf(leaves, "function_inventory_receipt__function", "r-login")

    # The same loss without the login receipt is missing evidence, not a hard dependency.
    _, _, gaps, unknown = outcome(lose(without(moved, "function_inventory_receipt", "r-login"), "east"))
    assert (gaps, unknown) == (base_gaps, {("shop", "login", "coverage-missing")})

    # An alternate whose failure domain nobody recorded cannot establish continuity.
    _, _, gaps, unknown = outcome(lose(without(data, "failure_domain_membership", "m-west"), "east"))
    assert (gaps, unknown) == (base_gaps, {("shop", "login", "domain-not-recorded")})


def test_withdrawn_cluster_without_domain_does_not_mask_disqualified_alternate():
    data = records()
    base_gaps = {("shop", "queue", "no-placement"), ("shop", "search", "no-solution")}

    # Provider idp runs on east (withdrawn, room-a), south (withdrawn, no domain), and north (surviving, room-a).
    # north is already disqualified by sharing room-a with east, so south's missing domain must not suppress the gap.
    case = copy.deepcopy(data)
    case["cluster"].append({"id": "south", "role": "worker-role"})
    next(b for b in case["cluster_service_binding"] if b["id"] == "b-idp-alt")["cluster"] = "north"
    case["cluster_service_binding"].append({"id": "b-idp-south", "service": "idp", "cluster": "south"})
    case["cluster_withdrawal"] = [
        {"id": "loss-east", "cluster": "east"},
        {"id": "loss-south", "cluster": "south"},
    ]
    _, _, gaps, unknown = outcome(case)
    assert gaps == base_gaps | {("shop", "login", "no-independent-placement")}
    assert unknown == set()

    # Adding a surviving placement on west (room-b) that does not share east's domain leaves continuity genuinely
    # unknown because south's unrecorded domain could still match west.
    with_candidate = copy.deepcopy(case)
    with_candidate["cluster_service_binding"].append({"id": "b-idp-west", "service": "idp", "cluster": "west"})
    _, _, gaps, unknown = outcome(with_candidate)
    assert gaps == base_gaps
    assert unknown == {("shop", "login", "domain-not-recorded")}
