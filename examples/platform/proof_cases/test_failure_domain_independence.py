"""Failure-domain independence per failure type: building alias collapse, unknown power feed, and proven separation.

Expectation source: decisions/platform-dependency-gaps.md, section "Failure-domain independence per failure type".
All expected rows and leaf premises are written by hand from the authored records below, never read from the engine.
"""

import copy

import pytest

from case_support import verified

GAP = "dependency_gap"
GAP_UNKNOWN = "dependency_gap_unknown"
SHARED = "shared_failure_domain"
INDEPENDENT = "failure_domain_independent"
INDEPENDENCE_UNKNOWN = "failure_domain_independence_unknown"
NO = "no"


def base_records():
    """Minimal topology with one consumer (shop), one provider (idp) serving login on clusters east and west."""
    from management_probes import _committed

    function = lambda key: {"id": key, "recovery_allowed": NO, "open_by_design": NO}
    service = lambda key, product: {"id": key, "product": product, "role": "app-role", "step": 1}
    has_offer_port = "port" in _committed().kinds["offer"].slots
    offer = {"id": "o-login", "product": "idp-app", "function": "login"}
    if has_offer_port:
        offer["port"] = 443
    return {
        "zone": [{"id": "inner", "outside": NO, "entry_boundary": NO, "isolated_recovery": NO, "workload": "yes"}],
        "cluster_class": [{"id": "shared"}],
        "platform_role": [{"id": "app-role", "zone": "inner", "cluster_class": "shared", "runs_images": "yes",
                           "build_authority": NO}],
        "function": [function("login")],
        "product": [{"id": "shop-app"}, {"id": "idp-app"}],
        "offer": [offer],
        "demand": [{"id": "d-login", "product": "shop-app", "function": "login"}],
        "service": [service("shop", "shop-app"), service("idp", "idp-app")],
        "cluster_role": [{"id": "worker-role", "control_placement": "local"}],
        "cluster": [{"id": "east", "role": "worker-role"}, {"id": "west", "role": "worker-role"}],
        "cluster_service_binding": [
            {"id": "b-shop", "service": "shop", "cluster": "east"},
            {"id": "b-idp-east", "service": "idp", "cluster": "east"},
            {"id": "b-idp-west", "service": "idp", "cluster": "west"},
        ],
        "function_inventory_receipt": [{"id": "r-login", "function": "login"}],
    }


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state


def leaf(leaves, relation, key):
    return any(rel == relation and row[0] == key for rel, row in leaves)


def leaf_pair(leaves, relation, first, second):
    return (relation, (first, second)) in leaves


def test_aliased_building_codes_collapse_to_one_domain():
    """Two distinct provider building codes linked by std-identity same_as collapse to one building domain."""
    data = base_records()
    data["failure_domain"] = [
        {"id": "bldg-prov-a", "domain_kind": "building", "same_as": ["bldg-prov-b"]},
        {"id": "bldg-prov-b", "domain_kind": "building"},
        {"id": "hall-e", "domain_kind": "hall", "contained_in": "bldg-prov-a"},
        {"id": "hall-w", "domain_kind": "hall", "contained_in": "bldg-prov-b"},
    ]
    data["failure_domain_membership"] = [
        {"id": "m-east", "cluster": "east", "domain": "hall-e"},
        {"id": "m-west", "cluster": "west", "domain": "hall-w"},
    ]
    data["cluster_withdrawal"] = [{"id": "loss-east", "cluster": "east"}]

    model, state = outcome(data)
    shared = state.derived.get(SHARED, set())
    independent = state.derived.get(INDEPENDENT, set())
    gaps = state.derived.get(GAP, set())
    gap_unknown = state.derived.get(GAP_UNKNOWN, set())

    # Aliased building codes collapse to one building failure domain; no false independence.
    assert {("east", "west", "building"), ("west", "east", "building")} <= shared
    assert ("east", "west", "building") not in independent
    assert ("west", "east", "building") not in independent

    # Withdrawing east leaves no surviving independent placement for login on west.
    hard_gap = ("shop", "login", "no-independent-placement")
    assert gaps == {hard_gap}
    assert gap_unknown == set()

    # Both the shared building conclusion and the dependency gap pass independent checker verification
    # and retain the std-identity alias and physical containment premises.
    shared_leaves = verified(SHARED, ("east", "west", "building"), state=(model, state))
    assert leaf_pair(shared_leaves, "referent__same_as", "bldg-prov-a", "bldg-prov-b")
    assert leaf_pair(shared_leaves, "failure_domain__contained_in", "hall-e", "bldg-prov-a")
    assert leaf_pair(shared_leaves, "failure_domain__contained_in", "hall-w", "bldg-prov-b")

    gap_leaves = verified(GAP, hard_gap, state=(model, state))
    assert leaf(gap_leaves, "cluster_withdrawal__cluster", "loss-east")
    assert leaf(gap_leaves, "function_inventory_receipt__function", "r-login")
    assert leaf_pair(gap_leaves, "referent__same_as", "bldg-prov-a", "bldg-prov-b")


def test_two_halls_without_power_evidence_are_explicitly_unknown():
    """Distinct halls with unknown or un-receipted power feeds stay explicitly unknown, never falsely independent."""
    data = base_records()
    data["failure_domain"] = [
        {"id": "bldg-a", "domain_kind": "building"},
        {"id": "bldg-b", "domain_kind": "building"},
        {"id": "hall-a", "domain_kind": "hall", "contained_in": "bldg-a"},
        {"id": "hall-b", "domain_kind": "hall", "contained_in": "bldg-b"},
    ]
    data["failure_domain_membership"] = [
        {"id": "m-east", "cluster": "east", "domain": "hall-a"},
        {"id": "m-west", "cluster": "west", "domain": "hall-b"},
    ]

    model, state = outcome(data)
    shared = state.derived.get(SHARED, set())
    independent = state.derived.get(INDEPENDENT, set())
    unknown = state.derived.get(INDEPENDENCE_UNKNOWN, set())

    # No power evidence: never falsely independent and never falsely shared.
    assert ("east", "west", "power") not in independent
    assert ("west", "east", "power") not in independent
    assert ("east", "west", "power") not in shared
    assert ("west", "east", "power") not in shared
    assert {
        ("east", "west", "power", "power-chain-unproven"),
        ("west", "east", "power", "power-chain-unproven"),
    } <= unknown
    verified(INDEPENDENCE_UNKNOWN, ("east", "west", "power", "power-chain-unproven"), state=(model, state))

    # Recording power feeds without complete PowerChainReceipt coverage still leaves power independence unknown.
    unreceipted = copy.deepcopy(data)
    unreceipted["failure_domain"].extend([
        {"id": "feed-a", "domain_kind": "power_feed"},
        {"id": "feed-b", "domain_kind": "power_feed"},
    ])
    unreceipted["power_feed_link"] = [
        {"id": "pf-a", "domain": "hall-a", "feed": "feed-a"},
        {"id": "pf-b", "domain": "hall-b", "feed": "feed-b"},
    ]
    model_u, state_u = outcome(unreceipted)
    assert ("east", "west", "power") not in state_u.derived.get(INDEPENDENT, set())
    assert ("east", "west", "power", "power-chain-unproven") in state_u.derived.get(INDEPENDENCE_UNKNOWN, set())
    verified(INDEPENDENCE_UNKNOWN, ("east", "west", "power", "power-chain-unproven"), state=(model_u, state_u))


def test_proven_power_separation_produces_verified_witness():
    """Both a cited PowerSeparationClaim and complete disjoint PowerChainReceipt coverage produce verified witnesses."""
    base = base_records()
    base["failure_domain"] = [
        {"id": "bldg-a", "domain_kind": "building"},
        {"id": "bldg-b", "domain_kind": "building"},
        {"id": "hall-a", "domain_kind": "hall", "contained_in": "bldg-a"},
        {"id": "hall-b", "domain_kind": "hall", "contained_in": "bldg-b"},
    ]
    base["failure_domain_membership"] = [
        {"id": "m-east", "cluster": "east", "domain": "hall-a"},
        {"id": "m-west", "cluster": "west", "domain": "hall-b"},
    ]

    # Ground 1: cited PowerSeparationClaim proves power independence with verified claim premises.
    by_claim = copy.deepcopy(base)
    by_claim["power_separation_claim"] = [{"id": "sep-halls", "first": "hall-a", "second": "hall-b"}]
    model_c, state_c = outcome(by_claim)
    assert {("east", "west", "power"), ("west", "east", "power")} <= state_c.derived.get(INDEPENDENT, set())
    assert ("east", "west", "power", "power-chain-unproven") not in state_c.derived.get(INDEPENDENCE_UNKNOWN, set())
    claim_leaves = verified(INDEPENDENT, ("east", "west", "power"), state=(model_c, state_c))
    assert leaf(claim_leaves, "power_separation_claim__first", "sep-halls")
    assert leaf(claim_leaves, "power_separation_claim__second", "sep-halls")

    # Ground 2: complete PowerChainReceipt coverage over disjoint feeds proves power independence with verified witness.
    by_chain = copy.deepcopy(base)
    by_chain["failure_domain"].extend([
        {"id": "feed-a", "domain_kind": "power_feed"},
        {"id": "feed-b", "domain_kind": "power_feed"},
    ])
    by_chain["power_feed_link"] = [
        {"id": "pf-a", "domain": "hall-a", "feed": "feed-a"},
        {"id": "pf-b", "domain": "hall-b", "feed": "feed-b"},
    ]
    by_chain["power_chain_receipt"] = [
        {"id": "rcpt-a", "domain": "hall-a"},
        {"id": "rcpt-b", "domain": "hall-b"},
    ]
    model_p, state_p = outcome(by_chain)
    assert {("east", "west", "power"), ("west", "east", "power")} <= state_p.derived.get(INDEPENDENT, set())
    assert ("east", "west", "power", "power-chain-unproven") not in state_p.derived.get(INDEPENDENCE_UNKNOWN, set())
    chain_leaves = verified(INDEPENDENT, ("east", "west", "power"), state=(model_p, state_p))
    assert leaf(chain_leaves, "power_chain_receipt__domain", "rcpt-a")
    assert leaf(chain_leaves, "power_chain_receipt__domain", "rcpt-b")
    assert leaf(chain_leaves, "power_feed_link__feed", "pf-a")
    assert leaf(chain_leaves, "power_feed_link__feed", "pf-b")

    # Counter-case: if the two power feeds are proven aliases via std-identity, power is shared, never independent.
    aliased_feeds = copy.deepcopy(by_chain)
    next(d for d in aliased_feeds["failure_domain"] if d["id"] == "feed-a")["same_as"] = ["feed-b"]
    model_a, state_a = outcome(aliased_feeds)
    assert ("east", "west", "power") not in state_a.derived.get(INDEPENDENT, set())
    assert {("east", "west", "power"), ("west", "east", "power")} <= state_a.derived.get(SHARED, set())
    aliased_leaves = verified(SHARED, ("east", "west", "power"), state=(model_a, state_a))
    assert leaf_pair(aliased_leaves, "referent__same_as", "feed-a", "feed-b")
