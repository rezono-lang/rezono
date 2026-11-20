---
decider: [platform]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: platform-five-scenes
---

# Organize the reference platform around five scenes

The reference platform in `examples/platform/` currently tracks 68 acceptance questions in [`questions.yaml`](../examples/platform/questions.yaml), spread across independent test cases with no single narrative sequence, no top-level README, no import of [`std-loop`](../packs/std-loop/pack.yaml), and no authored [`std-decision`](../packs/std-decision/README.md) fact rows in `examples/platform/facts/`. This decision organizes the example into one coherent story told in five operational scenes, establishes where every question is assigned, defines how the platform integrates `std-loop` and `std-decision`, specifies the two live publication counts reported in `examples/platform/README.md`, and sets the contract for one offline-replayable recorded run per scene. [Decision heads](decision-heads.md) · [Platform decision standing](platform-decision-standing.md) · [Safe transition rounds](safe-step-rounds.md)

## 1. The five scenes and their order

Every acceptance question in [`examples/platform/questions.yaml`](../examples/platform/questions.yaml) belongs to exactly one of five scenes, or is explicitly placed in `outside_scenes` with a written reason. No question is dropped.

| Scene | Slug | Title | What it demonstrates |
| --- | --- | --- | --- |
| 1 | `build-from-empty` | Build from empty | From governing decisions to a running cluster, in derived order: topology placement, fleet membership, required flows, fine-grained firewall rules, same-zone network policies, rendered policy files, product offers and demands, and safe startup from an empty scope. |
| 2 | `tenant-request` | A tenant submits a request | Whether a request fits, who approves it, and what is delivered: tenant request files, catalog entity rendering, delivery part closure, delivery status reporting, and tenant-scoped publication witnesses and access. |
| 3 | `change` | A change | First the difference, then the safe steps: fixed policy changes (entry TLS termination, relaxed recovery isolation, alternative providers), expiring vendor support windows, product phase-out and succession handoff, and capacity admission tipping points. |
| 4 | `failure-or-drift` | A failure or drift | A finding with evidence from both sides: live service health and telemetry observation, runtime and management outages, dependency gaps, backup age and recovery routes, router rule drift, reference CMDB comparison and identity conflicts, and isolated dataset restore while management stays offline. |
| 5 | `auditor-visits` | The auditor visits | Who may do what, who decided it, and what is proven: cluster access rights, membership withdrawal and tenant isolation, TLS certificate findings and renewal, release licences and sourced product provenance, decision and norm standing with review-after-replacement, network policy origins, and explicit unknown outcomes with reasons. |

Within any milestone, unfinished work in the lowest-numbered incomplete scene takes priority over higher scenes. Questions assigned to `outside_scenes` keep their milestone and follow the five scenes.

## 2. Where the scene assignment lives

The canonical scene assignment lives in [`examples/platform/scenes.yaml`](../examples/platform/scenes.yaml) using format `rezono.platform.scenes/1`.

Keeping the assignment in a sibling file beside `questions.yaml` preserves the strict `rezono.questions/1` contract and avoids churning the compiled pack's SHA-256 definition hash when scene metadata is updated.

The document has three top-level keys:

- `format`: literal string `rezono.platform.scenes/1`.
- `scenes`: mapping keyed by integers `1` through `5`, each with non-empty `slug`, `title`, and `summary`.
- `questions`: mapping keyed by every acceptance question `id` from `examples/platform/questions.yaml`, with no missing and no extra keys. Each value is a mapping with:
  - `scene`: an integer in `1..5` or the string `outside_scenes`.
  - `reason`: required non-empty text when `scene` is `outside_scenes`; omitted for numbered scenes.

### Complete assignment of the 68 acceptance questions

| Scene | Count | Question IDs |
| --- | --- | --- |
| 1. Build from empty | 16 | `checked-network-policy-rendering`, `cluster-fleet-membership`, `cluster-network-implementation`, `cluster-projection-completeness`, `cluster-required-flows`, `cluster-service-placement`, `cluster-worker-machine-stack`, `cluster-worker-network`, `cross-zone-firewall-rules`, `dependency-order`, `granted-listener-ports`, `postgresql-default-transport`, `provider-selection-evidence`, `safe-platform-startup`, `same-zone-network-policy`, `workload-address-ownership` |
| 2. A tenant submits a request | 6 | `catalog-entry-rendering`, `delivery-status-rendering`, `product-part-closure`, `readable-publication-witnesses`, `tenant-publication-access`, `tenant-request-file` |
| 3. A change | 12 | `admission-outcomes-and-free-capacity`, `alternative-providers`, `capacity-admission-threshold`, `entry-tls-firewall-change`, `entry-tls-flow-change`, `kubernetes-series-support-evidence`, `recovery-isolation-firewall-change`, `recovery-isolation-flow-change`, `successor-runtime-impacts`, `successor-support-window`, `support-ending-within-window`, `version-support` |
| 4. A failure or drift | 15 | `backup-age-and-inventory`, `backup-capture-and-readback`, `backup-storage-routes`, `cmdb-placement-authority`, `cmdb-placement-drift`, `comparison-report`, `current-service-health`, `dependency-gaps`, `management-recorder-availability`, `management-router-drift`, `management-telemetry-routes`, `observation-event-time-validity`, `offline-management-dataset-restore`, `reference-identity-conflicts`, `runtime-and-management-outage` |
| 5. The auditor visits | 17 | `conflicting-placement-decisions`, `decision-review-after-replacement`, `default-transport-publication-grounds`, `effective-decision-standing`, `keycloak-release-evidence`, `management-certificate-findings`, `management-certificate-renewal`, `management-cluster-rights`, `management-membership-withdrawal`, `management-tenant-access-isolation`, `network-policy-origins`, `norm-standing`, `product-release-publication-grounds`, `registry-release-licence`, `service-release-licences`, `support-without-vendor-evidence`, `unknown-time-boundaries` |
| `outside_scenes` | 2 | `role-and-zone-attribute-findings` (pack-level regression check verifying that core rules read role and zone attributes rather than hardcoded identifiers across every scene); `standard-pack-imports` (pack-level dependency pinning check verifying imported standard packs and their SHA-256 digests across the whole example) |

## 3. Importing `std-loop`

[`examples/platform/pack.yaml`](../examples/platform/pack.yaml) must import `std-loop` from `../../packs/std-loop` pinned to its current pack SHA-256 digest.

The platform consumes the reconciliation relations provided by `std-loop` (`declared`, `needed`, `known`, `waiting`, `ready`, `done`, `stuck`, `drift`, `fixed_point`, `plan`, `round_outcome`, `unblocked`, `loop_certified_batch`, and `loop_selected_batch`) rather than rebuilding loop mechanics in custom rules. No `.dl` file under `examples/platform/rules/` may redeclare any of those core loop relations.

## 4. Scene decisions as `std-decision` facts

Every governing decision used across the five scenes must be authored as a typed `decision` row under `examples/platform/facts/` following [`std-decision`](../packs/std-decision/README.md), together with its `subject` row, a `reference_date` row for the main platform publication, and a `platform_decision_binding` row ([`schema/decision_standing.yaml`](../examples/platform/schema/decision_standing.yaml), [`rules/decision_standing.dl`](../examples/platform/rules/decision_standing.dl)).

- Every non-proposed `decision` row in `examples/platform/facts/` must specify a non-empty `decider` list, a `decided_on` date (`YYYY-MM-DD`), a `valid_from` date (`YYYY-MM-DD`), and the matching `valid_from_day` integer (`YYYYMMDD`).
- Extend `PlatformDecisionArea` in `examples/platform/schema/decision_standing.yaml` with `backup_policy` and `access_policy` alongside the existing areas so every scene is explicitly grounded in at least one in-force decision binding:
  - **Scene 1:** `placement` and `zone_matrix`
  - **Scene 2:** `capacity`, `shared_cost`, and `review`
  - **Scene 3:** `product_stance`
  - **Scene 4:** `backup_policy`
  - **Scene 5:** `exclusion` and `access_policy`
- In the compiled main publication on the pack's `reference_date`, every bound in-force scene decision must appear in `in_force_on` and `effective_platform_decision`, and `in_force_without_decider` must be empty.

## 5. README overview and live publication counts

`examples/platform/README.md` introduces the reference platform through the five scenes—naming each scene's title from `examples/platform/scenes.yaml`—and states two exact counts verified directly against the complete (`checker`) live publication of `examples/platform/`:

1. **Decisions (`decisions`):** the number of distinct decision identifiers currently in force on the publication's reference date, counted from `relations/in_force_on.json`:
   `len({row["key"][0] for row in published["in_force_on"]})`. This count must be positive.
2. **Produced objects (`produced objects`):** the total number of derived rows in the complete publication across the platform's concrete operational object relations:
   - `cluster_service_placement`
   - `cluster_control_host`
   - `cluster_fleet_member`
   - `cluster_worker_host`
   - `cluster_worker_interface`
   - `cluster_machine_stack`
   - `cluster_network_stack`
   - `cluster_firewall_rule`
   - `cluster_in_zone_policy`
   - `managed_cluster_right`
   - `tenant_delivery_item`

Raw input facts, intermediate helper relations (such as `asks`, `provides`, `needs`, `flow`, and `crossing`), zone-level overview summaries (`firewall_rule`, `in_zone_policy`), and diagnostic findings (such as drift, outage, or policy-violation rows) are excluded from the produced-object count so that the figure measures derived operational outputs rather than inputs or alerts.

`examples/platform/README.md` must include a summary statement matching `<D> decisions produce <O> produced objects`, and the verification test checks that `D` and `O` equal the live publication's decision count and produced-object count.

## 6. Offline-replayable recorded run per scene

Each of the five scenes has one recorded reconciliation run stored under `examples/platform/recordings/scene-<number>-<slug>/` (for example `examples/platform/recordings/scene-1-build-from-empty/`). Each scene directory holds two files:

- `recording.json`: a typed `std-loop` recording accepted unmodified by [`loop/recording_input.py`](../loop/recording_input.py) (`load_recording` returning a `TypedRecording` pinned to `packs/std-loop`) and replayed completely offline through [`loop/replay.py`](../loop/replay.py) (`replay_report(..., report_limit=True)`) with no cluster access.
- `manifest.json`: scene recording metadata containing:
  - `scene`: integer `1`..`5` matching the directory.
  - `origin`: either `"real"` or `"hand-written"`.
  - `expected_plans`: non-empty list of per-round plan lists that offline replay of `recording.json` must reproduce identically.
  - `expected_outcome`: expected terminal replay state (`"success"` or `"failure"`).
  - When `origin` is `"real"`: non-empty `captured_on` date (`YYYY-MM-DD`) and non-empty `capture_evidence` identifier or digest tying the recording to a real cluster run.

Origin requirements follow the platform acceptance rules ([safe transition rounds](safe-step-rounds.md)):

- **Scene 1 (`build-from-empty`)** and **Scene 4 (`failure-or-drift`)** must have `origin: "real"`, captured from genuine cluster startup and offline-management restore runs.
- **Scene 2 (`tenant-request`)**, **Scene 3 (`change`)**, and **Scene 5 (`auditor-visits`)** may begin with `origin: "hand-written"` and be upgraded to `"real"` later; every manifest must declare its actual origin honestly.

## 7. Verification

[`examples/platform/test_five_scenes.py`](../examples/platform/test_five_scenes.py) enforces this decision with five tests:

- `test_every_question_belongs_to_one_scene_or_outside_with_reason` (active): checks `examples/platform/scenes.yaml` against `examples/platform/questions.yaml`.
- `test_platform_imports_std_loop` (`M2`): checks the pinned `std-loop` import in `examples/platform/pack.yaml`, forbids redeclaring core loop relations under `examples/platform/rules/`, and compiles the pack with `std-loop` rules loaded.
- `test_scene_decisions_are_std_decision_facts` (`M2`): checks authored `std-decision` facts with decider and date, scene bindings across all five scenes, and `in_force_on` / `effective_platform_decision` / zero `in_force_without_decider` in the compiled publication.
- `test_platform_readme_names_five_scenes_and_matches_publication_counts` (`M2`): checks `examples/platform/README.md` names all five scenes and matches the live publication's decision and produced-object counts.
- `test_each_scene_has_an_offline_replayable_recorded_run` (`M2`): checks that all five scene recordings exist, declare `origin` (with `"real"` required for scenes 1 and 4), load as typed `std-loop` recordings, and replay offline to their exact `expected_plans` and `expected_outcome`.

## Alternatives

- **Add a `scene` field directly inside `examples/platform/questions.yaml`.** Rejected because `questions.yaml` is part of the compiled pack definition hash and validated against `rezono.questions/1`; keeping scene ordering in a sibling `scenes.yaml` avoids schema extension and pin churn.
- **Count raw YAML lines or all derived relations in `examples/platform/README.md`.** Rejected because counting raw rows blurs inactive/superseded decisions with governing ones, and counting every intermediate predicate inflates the object count with helper joins and diagnostic findings.
- **Store `origin` and `expected_plans` inside `recording.json`.** Rejected because `loop/recording_input.py` enforces a closed key set on typed recordings; placing scene metadata in a sibling `manifest.json` keeps `recording.json` directly replayable by the existing loop CLI and loader.
