# Reference platform: five scenes

The `platform-core` example pack in `examples/platform/` models a multi-cluster Kubernetes platform and its tenant delivery workflow as a verifiable Rezono specification. It is organized around five operational scenes defined in [`scenes.yaml`](scenes.yaml) and grounded in [`decisions/platform-five-scenes.md`](../../decisions/platform-five-scenes.md).

In the complete (`checker`) publication on the platform's reference date (`2026-11-20`), **9 decisions produce 121 produced objects**.

## Live publication counts

The two headline counts above come directly from the compiled complete publication of `examples/platform/`:

- **Decisions (`9`):** distinct governing [`std-decision`](../../packs/std-decision/README.md) records in force on the reference date (`relations/in_force_on.json`), authored in [`facts/decisions.yaml`](facts/decisions.yaml) and bound to platform areas via `platform_decision_binding`.
- **Produced objects (`121`):** total derived rows across the platform's concrete operational object relations (`cluster_service_placement`, `cluster_control_host`, `cluster_fleet_member`, `cluster_worker_host`, `cluster_worker_interface`, `cluster_machine_stack`, `cluster_network_stack`, `cluster_firewall_rule`, `cluster_in_zone_policy`, `managed_cluster_right`, and `tenant_delivery_item`), excluding raw input facts, intermediate helper relations, zone-level overview summaries, and diagnostic findings.

## The five scenes

Every acceptance question in [`questions.yaml`](questions.yaml) is assigned in [`scenes.yaml`](scenes.yaml) to one of five scenes in order (or to `outside_scenes` for pack-wide invariants and dependency checks):

| Scene | Slug | Title | Summary |
| --- | --- | --- | --- |
| 1 | `build-from-empty` | Build from empty | From governing decisions to a running cluster, in derived order: topology placement, fleet membership, required flows, fine-grained firewall rules, same-zone network policies, rendered policy files, product offers and demands, and safe startup from an empty scope. |
| 2 | `tenant-request` | A tenant submits a request | Whether a request fits, who approves it, and what is delivered: tenant request files, catalog entity rendering, delivery part closure, delivery status reporting, and tenant-scoped publication witnesses and access. |
| 3 | `change` | A change | First the difference, then the safe steps: fixed policy changes (entry TLS termination, relaxed recovery isolation, alternative providers), expiring vendor support windows, product phase-out and succession handoff, and capacity admission tipping points. |
| 4 | `failure-or-drift` | A failure or drift | A finding with evidence from both sides: live service health and telemetry observation, runtime and management outages, dependency gaps, backup age and recovery routes, router rule drift, reference CMDB comparison and identity conflicts, and isolated dataset restore while management stays offline. |
| 5 | `auditor-visits` | The auditor visits | Who may do what, who decided it, and what is proven: cluster access rights, membership withdrawal and tenant isolation, TLS certificate findings and renewal, release licences and sourced product provenance, decision and norm standing with review-after-replacement, network policy origins, and explicit unknown outcomes with reasons. |

## Pack layout

- [`pack.yaml`](pack.yaml) declares `platform-core` and imports the pinned standard packs including `std-decision` and [`std-loop`](../../packs/std-loop/pack.yaml).
- [`schema/`](schema/) defines the LinkML schema modules across the `facts`, `intent`, and `observation` layers.
- [`rules/`](rules/) contains the Datalog derivation, standing, and finding rules.
- [`facts/`](facts/) holds the authored platform topology, policy, and decision facts.
- [`questions.yaml`](questions.yaml) and [`scenes.yaml`](scenes.yaml) list the 68 acceptance questions and their scene assignments.
- [`test_five_scenes.py`](test_five_scenes.py) verifies scene assignments, `std-loop` integration, `std-decision` standing, these README publication counts, and per-scene offline replay recordings.
