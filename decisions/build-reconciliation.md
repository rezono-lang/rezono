---
decider: [loop]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: build-reconciliation
---

# Derive build choices from observations

Use the build selection pack to derive which suites a recorded change reaches, which tasks are ready, waiting or stuck, which task claims may be released, and how milestone progress and release-1 completion stand. The `build/` pack takes over immediately from the Python scripts, running always on a pinned earlier engine commit of `main` so a broken engine commit can never block its own repair. The existing Python selector, red-list scanner and claim cleanup script remain strictly as fallback, executed only when the pack's publication is absent, checker-rejected or fails to compile. Discrepancies observed between the pack and the Python fallback are recorded as findings to fix, never as blockers. The pack uses the pinned `std-loop` sweep receipt (which imports `std-order`), `std-decision`, and `std-access` so coordinator and owner roles read verified publications directly. [Project vision](../docs/vision.md) · [Loop rules](../packs/std-loop/pack.yaml) · [Safe transition rounds](safe-step-rounds.md) · [Release 1 scope](release-1-scope.md) · [Code does not decide](code-does-not-decide.md)

## Observed kinds

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildRun` | A GitHub event and a protected engine checkout identify one input. Can a reviewer establish the event kind, exact diff base and head, engine commit and recorded observation time for a selection? |
| `BuildComponent` | Test-suite discovery observes an executable check standard. Which suite was available to select in this run, and was it a Python, Node or contract suite? A manifest alone does not establish test discovery. |
| `BuildManifest` | An exact regular Git blob contains a Python or Node declaration. Was a dependency declared at either endpoint of this observed range, and which blob carried it? |
| `BuildTestFile` | A source inventory records an actual file in a suite. Which test file can the suite account for? A package declaration does not enumerate its test files. |
| `BuildDependency` | The typed manifest import resolves a declared local dependency, or an explicit read binding establishes a file consumer. Is there a sourced dependency from this suite to that consumer at this cut? |
| `BuildPath` | The recorded Git diff contains a changed path. Was that path in the reader map's scope? A known path with an empty reader set is distinct from an unknown path. |
| `BuildPathReader` | The reader inventory identifies a path's owner or consumer. Does the observation make it directly selectable or supply a root whose transitive dependents also run? |

The typed capture reads manifests and source inventory without running candidate code. Read regular manifest blobs from both exact endpoints, recording their path, revision and blob. Use the package imports and the published test-file/read map for dependency and reader observations. A change that removes a declaration can still reach a suite through an edge observed at the base. The existing Python implementation provides a test oracle for manifest resolution, range and selection. Its result is not an input to the pack rules. [Current selector](../scripts/components.py)

Bind one immutable observation to each run attempt. Preserve the raw PR event head separately from the effective exact checkout when they differ. Preserve the actual merge-group event range. A complete capture binds the suite universe, diff paths, both endpoint manifest inventories and reader mapping to the same run and recorded time. A matching `LoopSweepReceipt` supplies the positive coverage relation. Input capture uses the recorded source event time. It never substitutes the wall clock. Verify the range, source identities, input digest and pinned earlier `main` engine commit before trusting the manifest. Unknown or incomplete input produces an explicit full-selection reason; engine failure or an absent or checker-rejected publication falls back to the Python selector with the reason recorded as a finding. [Observation contract](../contracts/observation.yaml) · [Manifest contract](../contracts/manifest.yaml)

## Selection and publication

A mapped path's direct readers run. Its transitive readers also seed ordinary recursive dependency rules. Treat file consumers and both endpoint declaration graphs as parts of this evidence. Direct-only readers do not seed closure. A known readerless document adds no suite. An unknown path requests every suite, with the source path as evidence. A missing same-run receipt, invalid dependency origin or invalid reader binding produces an explicit full-selection reason.

Publish `build_selected_job(run, component, reason)` with a proof per row. Publish `build_full_selection(run, reason)` separately. Verify one manifest per observed run attempt and read the selected suite set after the checker verifies the publication. Trusted output glue expands the suite IDs to the configured job and shard matrix. The first slice handles PR selection with supplied verified observations. A merge-group observation in this slice yields an explicit unsupported-policy reason. The existing merge-group checks remain in effect until their separate policy is modeled and compared. Fetching an untrusted revision is sufficient for capture. The pack, engine, dependencies and verifier execute from a pinned earlier commit of `main`.

## Task and queue observations

Derive task states from the imported `std-loop` relations using task prerequisites, current claims and observed PR state. Observe PR checks and run minutes with dated origins. Use `std-decision` to hold the effective claim lease, queue bounds and task priority limits. When choices are available, the language task precedes the core task, a queue of thirty denies a planner slot under the named decision, and an unfinished prerequisite keeps its task waiting. An outranked task cites its rank and the winning work. Unknown queue coverage or an incomplete inventory does not prove planner capacity: only the admitted member inventory of a pull listing does ([admission transport](admission-transport.md), section 6, queue pulls). [Decision library](../packs/std-decision/pack.yaml) · [Order library](../packs/std-order/pack.yaml)

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildTask` | An observed task declaration identifies a step and track. Which observed tasks does the standard loop class as ready, waiting or stuck at this cut? |
| `BuildPolicyDate` | The observation adapter derives the reference day from the recorded cut. Which policy day applies to this run? |
| `BuildTrackRank` | An effective decision assigns a track priority. Which ready task precedes another under those decision rows? |
| `BuildQueueLimit` | A decision supplies the planner threshold. Which threshold establishes or denies a free planner slot? |
| `BuildQueueReading` | An independent queue reader reports a count and event time. It establishes no count, because no rule can check a reported number against the pull requests it counts; it remains a record to compare. |
| `BuildQueueListing` | A pull listing of one base at the run's cut names the receipt of its protected read. Do the admitted `queue-listing` and `queue-pull` members of that receipt establish the queue, or is it missing, stale or contradicted? |

Publish the witnessed task relations (`build_task_ready`, `build_task_waiting`, `build_task_stuck`, `build_task_precedes`) and planner decisions (`build_planner_slot`, `build_planner_waiting`) for the coordinator and owner roles. The first task-order slice accepts supplied `std-loop` step and requirement observations and consults effective policy at the recorded reference date.

## Claim release

Evaluate expiry at the observation's recorded time. Read the effective lease duration from its decision, starting with four hours. Eligibility alone can yield only a plan. The same lease/generation authority must guard both opening a PR and deleting a claim, and the adapter must conditionally recheck generation, expiry and PR absence at deletion. A reopened or newly created PR, a renewed lease, or unreadable state prevents deletion. Verify absence of that exact generation with a completed read in the same run before reporting completion. An uncertain effect is reconciled under its original claim. Exercise expired, renewed and renewed-during-delete leases, a PR opened between the initial check and deletion, and a replacement ref before absence confirmation. Export `build_claim_release_plan`, `build_claim_held`, `build_claim_released`, `build_claim_release_discarded` and `build_claim_release_pending` as published relations so the coordinator reads them directly without recomputing lease policy. [Effect protocol](../contracts/effect.yaml) · [Claim model](../formal/Claims.tla) · [Build claim release](build-claim-release.md)

## Transition evidence

The earlier one-week parallel comparison gate is replaced by an **immediate cutover** with a pinned engine and strict Python fallback.

### Immediate cutover and Python fallback

- **CI suite selection:** CI chooses test suites directly from the published `build_selected_job` and `build_full_selection` relations of `build/` once the independent checker verifies the publication green (`rezono:proofs` and `rezono:schema` green and every required relation present).
- **Coordinator state and claim release:** The coordinator reads ready, waiting and stuck tasks (`build_task_ready`, `build_task_waiting`, `build_task_stuck`, `build_task_precedes`) and claim-release state (`build_claim_release_plan`, `build_claim_held`, `build_claim_released`, `build_claim_release_discarded`, `build_claim_release_pending`) from the verified publication of `build/`.
- **Thin reader with zero decisions:** Thin reader modules (`loop/build_cutover.py` for CI suite selection and `loop/build_coordinator_reader.py` for coordinator task and claim-release state) read the published relations and project them without making any selection, ordering or lease-expiry decision of their own. `loop/build_transition_choice.py` was the transitional comparison-week helper and is superseded by `loop/build_cutover.py`.
- **Python strictly as fallback:** The Python scripts (`scripts/components.py`, `scripts/red_list.py`, `scripts/release_claims.py`) execute **only** when the pack's publication is absent (`manifest is None` or `rows is None`), rejected by the checker (any non-green check, empty checks, or a missing required relation), or the pinned engine fails (`engine_error`). When a checker-verified publication is present, `python_fallback` is not invoked to decide the outcome.
- **Discrepancies are findings, never blockers:** Whenever an optional audit comparison (`python_audit`) runs alongside a checker-verified publication and differs from the pack's result, the verified pack result still stands (`source = "pack"`, `blocked = False`), and each discrepancy is recorded as a structured finding (`{"kind": "discrepancy", "run": ..., "surface": ..., "only_pack": [...], "only_python": [...]}`) to repair in a follow-up change.

### Pinned-engine invariant

`build/` MUST always execute using the compiler, publisher, checker and pack dependencies checked out from a **pinned earlier commit of `main`**, never from the candidate commit being evaluated. A broken compiler or engine change in a pull request or merge group can therefore never block its own repair.

- Record the pinned 40-lowercase-hex commit SHA as `engine_sha` in `build/engine-pin.yaml`.
- Update `build/engine-pin.yaml` only through an explicit pull request after the target commit has landed green on `main`.
- `loop/build_pinned_runner.py` reads `build/engine-pin.yaml` (`read_engine_pin(path)`) and validates before running (`validate_engine_pin(*, root, engine_sha, candidate_sha, main_ref="refs/remotes/origin/main")`) that both SHAs are 40 lowercase hex digits, that `engine_sha != candidate_sha`, and that `engine_sha` is an ancestor of `main_ref`. Any violation raises `ValueError`.

## Progress and release-1 completion

Milestone progress, release-1 completion and off-board release-1 work are derived relations in `build/` with proofs, published for roles readable by the coordinator and owner. [Release 1 scope](release-1-scope.md) · [Red list](../scripts/red_list.py)

### Observed kinds for progress

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildMilestone` | The six milestone marks (`M1`, `M2`, `M3`, `M4`, `extra`, `later`) with enum slot `scope` (`release_1` for `M1`–`M4`, `outside_release_1` for `extra` and `later`). Which milestones are tracked and which belong to release 1? |
| `BuildProgressScan` | A complete progress and off-board work scan bound to one verified `BuildRun` cut (`run`, `observed_at`, non-empty `source`). Only a unique scan at the cut tick counts; an earlier scan or conflicting scans at the cut yield no progress rows. |
| `BuildRedTest` | One red test currently observed on the board in a `BuildProgressScan` (`scan`, `test`, `milestone`). |
| `BuildGreenTransition` | One test observed in Git history to have carried a milestone mark and turned green at a recorded commit (`scan`, `test`, `milestone`, 40-hex `commit`). |
| `BuildOffboardWork` | One off-board release-1 work stream not represented as a red test on the board — such as repository files still awaiting migration to `rezono 1` (`0` of `N`) — with `scan`, `item`, `state` (`known` or `unknown`), optional integer counts `completed` and `total` (`>= 0`), optional `reason`, and non-empty `source`. |

### Derived progress relations

All four relations are declared in `build/rules/progress.dl` (over `build/schema/progress.yaml`, with labels in `build/labels/en.yaml` and shapes in `build/channels.yaml`) and carry a checker-verified proof per row:

- **`build_milestone_progress(run, milestone, green_count, red_count)`:** For every declared `BuildMilestone` at a verified cut with a unique `BuildProgressScan`, derives both `green_count` (distinct tests recorded in `BuildGreenTransition` for that milestone in the scan) and `red_count` (distinct tests recorded in `BuildRedTest` for that milestone in the scan). Both counts are exact integers (`0` when empty), each witnessed with its contributor digest.
- **`release_1_done(run, scan)`:** Holds at a verified cut with a unique `BuildProgressScan` if and only if all four release-1 milestones (`M1`, `M2`, `M3`, `M4`, with `scope = "release_1"`) are declared and zero red tests in `scan` carry any `M1`–`M4` milestone. Red tests carrying `extra` or `later` do not prevent `release_1_done`. An absent or conflicted scan never proves `release_1_done`.
- **`build_offboard_work_count(run, item, completed, total, remaining)`:** Holds for each `BuildOffboardWork` item in the cut's scan whose `state = "known"`, whose `completed` and `total` are present with `0 <= completed <= total`, and whose `source` is non-empty, with `remaining = total - completed`.
- **`build_offboard_work_unknown(run, item, reason)`:** Holds for each `BuildOffboardWork` item in the cut's scan that is not observable as a valid count — never silently omitted:
  - when `state = "unknown"` with a non-empty `reason`, emits that `reason`;
  - when `state = "unknown"` without a non-empty `reason`, emits `"unspecified-unknown-reason"`;
  - when `state = "known"` with missing `completed`/`total` or `completed > total`, emits `"incomplete-observation"`.

### Role-scoped publication (`std-access`)

`build/pack.yaml` imports `packs/std-access`. `build/facts/roles.yaml` declares at least the `coordinator` role (capabilities `[read, agent]`) and the `owner` role (capabilities `[read, review, administer]`). `build/rules/access.dl` grants `may_read` and `may_read_full` to every role holding the `read` capability across `role` and every input kind required to derive milestone progress, `release_1_done`, off-board release-1 work, task states and claim-release relations (without exposing protected admission tables to filtered roles). Publishing `build/` with `"may_read"` roles for `coordinator` and `owner` gives both roles the snapshots and checker-verified witnesses for all of those relations, while any role without the `read` capability receives none.
