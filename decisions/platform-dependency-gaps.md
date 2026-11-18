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

## Acceptance

The reader question `dependency-gaps` returns the result and its grounds from the publication. In `test_dependency_gaps.py::test_dependency_gaps`, hand-author one missing solution, one known solution with missing placement, and one function that stays served after losing a cluster. Move its alternate onto the failed cluster and remove a coverage receipt in separate cases to distinguish a hard dependency from missing evidence. Include an inventory disagreement with both source positions and an unmatched identity. Read the exact rows, their witnesses and the signed what-if differences. The publication only shows a conclusion to roles that can see all of its grounds.

Counting placements alone ignores shared failure domains and wrong functions. Comparing each register directly to the platform without a proved identity can turn a missing match into a conflict. Use the typed parts, identities and observed coverage for both cases. The acceptance fixture supplies an independent expected result. The register comparison remains a drift finding.
