---
decider: [platform]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: platform-dependency-gaps
---

# Report platform function dependency gaps

For each function a service needs, explain whether the design lacks a solution or its placement and whether loss of a cluster leaves the function unavailable. Report any disagreement between the cluster and machine inventories with the evidence from both.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Service demands, offers, provider choices and service placements | The platform design states each separately. These inputs retain the distinction between choosing a provider and placing it. Reuse the [platform rules](../examples/platform/rules/core.dl) and [placement rules](../examples/platform/rules/cluster_placement.dl). |
| Failure-domain membership and coverage | A topology design or direct, scoped inventory observation may establish membership of an identified placement. Add a typed statement only when current part and identity inputs cannot establish it. A complete inventory receipt is an independently observed property of a particular scope and cut. These facts are needed to decide whether an alternative remains available. |
| Cluster and machine inventories | The registers are separate reference sources. Retain the export revision, scope and source position of each assertion. Neither register can create or move an authoritative placement. |

An added membership or coverage kind represents a topology assertion or an observation, as opposed to the shape of the system that exported it. Its origin supplies a fact unavailable from the other input rows. Keep identity assertions in `std-identity`, with their own evidence.

## Rules and proof

Start with `needs` and the unmet or ambiguous provider cases. Follow the selected provider to its placements through `std-part` and resolve aliases through proven `std-identity` bindings. Retain the demand, choice or candidate inventory, placement and identity premises. Report an absent solution or placement only where the relevant inventory is complete. An uncovered or disputed key gives an explicit unknown outcome with the missing or conflicting grounds.

Compare the baseline with the ordinary what-if difference after withdrawing the affected cluster's availability in the hypothetical state. Use the same rules and leave observed facts intact. A second placement relieves the dependency when the proof shows it can still serve the same function through an independent failure domain. A second entry on the same cluster, an unrelated function or an unproved relationship cannot establish continuity. A hard dependency needs evidence for the relevant candidate set and for the absence of a viable alternative.

Compare the two inventories after joining a proved canonical machine or cluster identity within the stated scope. Publish the difference as drift. An unmatched alias or incomplete register scope leaves the comparison undecided, even when another source already proves the platform placement.

## Failure-domain independence per failure type

Two providers can report the same physical building under distinct provider codes, and two distinct hall names never prove separate electrical feeds. Comparing raw failure-domain name strings for inequality therefore produces false independence on both building failures and power failures.

### Typed failure domains, identity, and physical containment

Declare the following kinds in `examples/platform/schema/dependency_gaps.yaml` alongside `FailureDomainMembership`, `FunctionInventoryReceipt`, and `ClusterWithdrawal`:

- `FailureDomainKind` enum: `building`, `hall`, `power_feed`, `room`.
- `FailureType` enum: `building`, `power`.
- `FailureDomain` (`is_a: Referent` from `std-identity:identity`):
  - inherits `id`, `same_as` (`multivalued: true`), and `represented_by` (`multivalued: true`) so proven provider aliases live in `std-identity`;
  - `domain_kind` (`FailureDomainKind`, required): classifies the physical or electrical domain;
  - `contained_in` (`FailureDomain`, optional single-valued): states direct physical containment (for example a hall inside a building).
  - Bind `FailureDomain` and `contained_in` to `std-part` (`constituent`, `part_of`) in `examples/platform/views.yaml` so `std-part`'s `within(part, whole)` computes transitive containment and `part_cycle` enforces acyclicity.
- `PowerFeedLink` (`id`, `domain: FailureDomain`, `feed: FailureDomain`): states that a domain (a hall, room, building, or downstream feed) draws power from a `power_feed` domain.
- `PowerChainReceipt` (`id`, `domain: FailureDomain`): an observation receipt confirming complete coverage of the power chain feeding `domain`.
- `PowerSeparationClaim` (`id`, `first: FailureDomain`, `second: FailureDomain`): a cited topology assertion (carrying its own provenance) stating that `first` and `second` have independent power.

Existing `FailureDomainMembership` records (`id`, `cluster: Cluster`, `domain`) stay valid; when `domain` matches a `FailureDomain` id, the cluster inherits that domain's `std-identity` equivalence class (`equivalent`) and `std-part` containment (`within`) across aliases.

### Derived independence relations and proof obligations

In `examples/platform/rules/dependency_gaps.dl`, derive and output the following symmetric relations over pairs of distinct clusters `(cluster, other)` and `failure_type` (`"building"` or `"power"`):

1. `shared_failure_domain(cluster, other, failure_type)`:
   - For `"building"`: `cluster` and `other` reach equivalent `building`-kind `FailureDomain`s, directly or through `std-part` `within` composed with `std-identity` `equivalent`.
   - For `"power"`: `cluster` and `other` reach equivalent `power_feed`-kind `FailureDomain`s along `PowerFeedLink` chains (propagated from containing domains via `within` and across aliases via `equivalent`).
   - Any pair sharing an equivalent recorded domain or an enclosing `building` domain is also treated as shared in `shares_withdrawn_domain(provider, alt)`, so withdrawing one cluster never leaves an aliased placement in the same building as a surviving `independent_placement`.
2. `failure_domain_independent(cluster, other, failure_type)`:
   - For `"building"`: both `cluster` and `other` have recorded `building` domains (directly or via `within`) and `!shared_failure_domain(cluster, other, "building")`.
   - For `"power"`: `!shared_failure_domain(cluster, other, "power")` AND either:
     - a `PowerSeparationClaim` covers `(cluster, other)` (matching their domains, enclosing domains via `within`, or aliases via `equivalent`, in either argument order), OR
     - both clusters reach domains covered by `PowerChainReceipt`, both have at least one recorded `PowerFeedLink` in that chain, and no feed in their chains is shared (modulo `std-identity` `equivalent` and `std-part` `within`).
3. `failure_domain_independence_unknown(cluster, other, failure_type, reason)`:
   - For `"power"`: whenever two clusters have physical `FailureDomain` memberships, do not have `shared_failure_domain(cluster, other, "power")`, and satisfy neither power-independence ground above, emit `failure_domain_independence_unknown(cluster, other, "power", "power-chain-unproven")`. Distinct hall names or un-receipted feed rows never establish power independence.

Every positive row in `shared_failure_domain`, `failure_domain_independent`, `failure_domain_independence_unknown`, and `dependency_gap` carries a checker-verifiable witness retaining its `std-identity` (`referent__same_as`), `std-part` (`contained_in` / `within`), `PowerSeparationClaim`, or `PowerChainReceipt` and `PowerFeedLink` premises.

## Acceptance

The reader question `dependency-gaps` returns the result and its grounds from the publication. In `test_dependency_gaps.py::test_dependency_gaps`, hand-author one missing solution, one known solution with missing placement, and one function that stays served after losing a cluster. Move its alternate onto the failed cluster and remove a coverage receipt in separate cases to distinguish a hard dependency from missing evidence. Include an inventory disagreement with both source positions and an unmatched identity. Read the exact rows, their witnesses and the signed what-if differences. The publication only shows a conclusion to roles that can see all of its grounds.

In `examples/platform/proof_cases/test_failure_domain_independence.py`, verify separately that:

1. Two distinct provider codes proven to refer to the same building through `std-identity` (`same_as`) collapse to one building domain on building failure and produce no false surviving placement.
2. Two halls with unknown power feed (or un-receipted power feeds) leave power independence explicitly `unknown` (`power-chain-unproven`), never falsely independent.
3. A proven power separation — either via a cited `PowerSeparationClaim` or via complete `PowerChainReceipt` coverage over disjoint `PowerFeedLink` chains — produces a checker-verified witness confirming `failure_domain_independent(..., "power")`, while aliased feeds still collapse to `shared_failure_domain(..., "power")`.

Counting placements alone ignores shared failure domains and wrong functions. Comparing each register directly to the platform without a proved identity can turn a missing match into a conflict. Use the typed parts, identities and observed coverage for both cases. The acceptance fixture supplies an independent expected result. The register comparison remains a drift finding.
