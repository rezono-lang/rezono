# Acceptance cases for platform derivations and proof visibility

The platform pack owns authored facts and derives results in its schema and rule modules. The independent Python model supplies expected rows. The following finite cases define acceptance for implementation. They do not report an observed deployment or a passing engine comparison.

## Classify roles and zones from facts

Declare zone attributes for outside, entry boundary, isolated recovery and workload, and role attributes for build authority and image execution. Join those attributes to endpoints and artifacts in the existing finding rules. Rename the five fixture identities external, entry, recovery, build and tenant to unused identifiers while preserving their attributes and references. After applying the same renaming to expected tuples, every relation must agree row for row. As a second case, keep identifiers unchanged and remove build authority from the builder role. A signed artifact from that builder must lose its verification witness. A name-only check would pass the first fixture by accident and fail these counterfactuals.

## Run the cluster example through the pack

Declare cluster identity, cluster role, control hosting policy, worker hosting policy, network-layer selection, node address bounds, endpoint address and service placement in the pack schema. Ownership, physical host and network attachment are distinct references. Use generic rules to join instance placement to role attributes. Resolve named products through the selected role binding. Serialize policy and bootstrap outputs from those derived rows.

| Finite fixture | Required result and evidence |
| --- | --- |
| One management cluster, one infrastructure cluster and two guest clusters | Each guest owns one control endpoint hosted on management. Both endpoints have distinct addresses inside the management range. Each virtual worker is physically hosted on infrastructure and has an interface inside its own guest range. Witnesses identify the guest, role policy, host and address assignment. |
| Self-hosted recovery plus external storage | Recovery hosts its own control and worker. Storage appears as an external target. It has no Kubernetes control endpoint, CNI or fleet membership. |
| Cilium with Hubble bound to the network role | Every Kubernetes cluster derives this policy and observation layer exactly once. Replacing the binding changes the selected products for all matching clusters with no rule edit. |
| Endpoint outside its attached network or a repeated address | The invalid assignment yields a finding with its address and relevant bounds or conflicting owner. Never generate a usable rule from that assignment. |

CI must compare the complete portable relation inventory and each relation's complete tuple set between the independently calculated reference and the engine. Cover cluster ownership and hosts, guest network identity, network layer, machine inputs, endpoint addresses, flows, both rule projections, positive and negative cases, excess-access evidence and findings. Treat an absent relation, unexpected relation or extra row as a failure, including for empty expected sets. Compare typed values and report the first differing relation with one missing or unexpected tuple. Test both the original fixture and the renamed fixture. Re-running the independent writer alone cannot establish engine agreement.

## Compute negative cases from all applicable permissions

A candidate consists of source, listening destination, protocol and port. Keep the listener inventory independent of permissions. First union all applicable firewall allowances. A cross-zone candidate outside that union has a firewall-denial witness. For remaining candidates, evaluate the applicable service-isolation policies, including same-zone traffic. A denied candidate at this stage has a service-isolation witness. Report a positive case only if every applicable layer permits it. Keep excess firewall reachability visible even when service isolation blocks the final connection.

Use four synthetic sources or destinations in two zones. Source A may reach listener X through rule R1 and listener Y through rule R2, both on TCP 443. Listener Z has the same transport and zone with no allowance. Peer B shares the source range with A. A→Y must survive the union even when enumerated as an alternative to R1. A→Z is denied at the firewall. B→X, with no service grant, is firewall-permitted by R1 and denied by service isolation. A→X, with its service grant, is permitted end to end. A non-listening destination produces no candidate. Compare the complete disjoint decision sets and reason witnesses. These cases use symbolic inputs and static model evaluation.

## Import and exercise the five standard packs

The platform manifest must declare all five local imports with verified definition digests. Load that manifest through the normal compiler, invoke the imported predicates through the platform bindings and validate each proof against the compiled snapshot. A similarly named local relation or a separately loaded library cannot satisfy the import case.

| Imported pack | Fixture, outcome and required proof |
| --- | --- |
| std-order | Author steps request→review and review→apply. Expect exactly those edges and request→apply in the three-element before relation. The transitive proof uses both authored edges. Use that order for stage readiness and per-tenant request order. |
| std-part | Author database→delivery and delivery→catalog-entry as direct part links. Expect within(database,catalog-entry) and outermost(database,catalog-entry). The witness includes both links. Use the same binding for product components. |
| std-identity | Two source records A and B identify the same database and report different text values for its edition. Expect both directed identity_conflict rows for that slot and no conflict for an equal-valued slot. Witness the equivalence and both incompatible source claims. |
| std-time | Author a support interval beginning at position 1, with neither an end nor an explicit unbounded end. Query position 3 on the same axis with a finite horizon. Expect end_not_recorded and judgement unknown/end_not_recorded. Witness the interval, axis, reference point and absence condition. A new end fact must invalidate the absence witness. |
| std-access | Give Elm read grants for its request of two cores and an independently issued four-core Elm quota row. The capacity conclusion fits has only Elm-readable fact leaves and its applicable grants. Reed has an independent quota and request. Elm has no may_read row for either Reed row. Remove Elm's quota grant and verify that the conclusion with that witness disappears from Elm's publication. The operator can still see fleet totals. |

For each tenant-visible conclusion, traverse the proof to its leaves under the reader's role. A filtered output row with a hidden witness fails acceptance. Quotas or published free-space observations must be independently readable evidence. A raw sum exposing another tenant's usage is unsuitable for that publication. The capacity case compares the authorized conclusion, grants and full witness chain for both roles.
