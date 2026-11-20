---
decider: [owner, loop, core, run]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: engine-epoch-run
---

# Run one engine epoch as a std-loop run, with one run vocabulary for every run

Rezono's own development is steered by Rezono's own relations. The build run already is a `std-loop` pack ([build reconciliation](build-reconciliation.md)), and the paid provider run is designed as a loop ([run-scoped reconciliation](loop-design.md), [run reconciliation](run-reconciliation.md)). The engine epoch run is the third: it takes one epoch of one pack from compile to distribution. Today a Python call sequence drives it, and the publisher stops it by raising an exception. This decision makes that run a `std-loop` run that orchestrates the steps and evaluates nothing itself. Following [code does not decide](code-does-not-decide.md), it gives each publisher check one fate: an input-integrity check stays in code, and a gate that decides whether an epoch may be published becomes a derived refusal. It names the one home of every run concept that the three runs share, so that no run concept is defined twice. The owner accepted the approach: orchestration only, evaluated by a pinned earlier engine, the checker independent, effects exactly once, "why published" as a derived relation whose witness hash goes into the epoch statement, and sealing later. [Loop rules](../packs/std-loop/pack.yaml) · [Publisher](../edge/publisher/rezono_publisher/publish.py) · [Epoch statement](../contracts/statement.yaml) · [Effect contract](../contracts/effect.yaml) · [Formal models](../formal/README.md)

## 1. Existing behavior

At `0d1a379d`:

- **The publisher stops on the first red finding.** [`publish.plan`](../edge/publisher/rezono_publisher/publish.py) computes every object of a publication and raises `Blocked` on the first red finding: a red engine check, a public-surface refusal, a theory flag, a missing or malformed rule IR or calculation IR, a malformed witness, a relation no definition accounts for, a checker error in the proofs (`rezono:proofs`), an uncovered role (`rezono:access`), a missing required conclusion (`publication_required`), images (`rezono:assets`), fact sources (`rezono:sources`) and admitted evidence (`rezono:evidence`). The command line turns `Blocked` into exit code 2, with the reason as a message on stderr. No relation says why an epoch was published or refused. The audit of [code does not decide](code-does-not-decide.md), at `8d1fa9c`, found the publisher in line with "code does not decide"; section 3.4 keeps to that audit and names the one check that came after it.
- **Signing and distribution are effects without a journal here.** The form builder writes `statement.json` beside each filtered role's form. The signature is cosign's bundle over those bytes, and [`statement.attach`](../publication/rezono_publication/statement.py) pushes the statement and signature as a referrer of the role's seal. The store's conditional put makes writing a form idempotent. Nothing in this repository records a signing or push attempt, so nothing derives whether one happened once.
- **The statement says what, not why.** An epoch statement (`rezono.epoch-statement/1`) binds the role's objects, snapshots, dataset, annotation and row roots. It never names `pack_sha256`, and a role's statement depends on nothing that role may not read. [Role epoch diffs](publication-role-diffs.md) specifies version 2, which adds `previous` and `diff` both or neither. That version is not built yet.
- **The build run** imports `std-loop` and `std-decision`. Its task relations are views over `unblocked`, `waiting` and `stuck`, and its readings cite `LoopSweepReceipt`. It also defines claims, a lease that the latest push starts, and the settling of a claim delete by a complete ref read: `BuildClaim`, `BuildClaimActivity`, `BuildClaimLease`, `BuildClaimDelete`, `BuildClaimRefRead` and the rules of `build/rules/claims.dl` and `build/rules/claim_release.dl`. Those rules are the derivation of the [Claims](../formal/Claims.tla) model, and nothing in them is specific to builds.
- **The provider run** imports no `std-loop`. `run/packs/cleanup` declares its own `Sweep` and `Attempt`. `run/packs/cleanup-deadline` declares an `Attempt` whose `CleanupAttemptState` enum copies the six values of `EffectState` in the effect contract. Its claims live in Python: `run/journal_claim.py` (a SQLite row per plan hash) and `run/git_claim.py` (a write-once Git ref, [shared claim](run-shared-claim.md)). `run/packs/dispatch` binds an approval to the exact plan hash.
- **`std-loop`** defines steps, requirements, completions, goals, expectations, observations, sweeps, sweep receipts, deadlines, recorded refusals and pending operations. A refusal can only be recorded (`LoopRefusal`), not derived. A pending operation is an input record with a run and a token and nothing else.

## 2. One run vocabulary

The vocabulary has two layers. The loop layer, sections 2.1 to 2.3, is how any run proceeds: steps, requirements, claims, effects, receipts and refusals. Its home is `std-loop`. The provider layer, section 2.4, is what each of the three runs is: a run that buys work from a provider, through order, claim, delivery, acceptance, payment and cleanup. This decision names that layer and its mapping as the target. It does not build or move it.

### 2.1 Inventory

| Concept | `std-loop` today | Build pack today | Provider run today | Engine epoch needs | One home after this decision |
| --- | --- | --- | --- | --- | --- |
| Run id | `LoopActiveRun.id`; every run-scoped record has a `run` slot | `BuildRun` (event, endpoints, engine, cut) | free `run` text in `cleanup`; none in `dispatch` | yes | `LoopActiveRun.id`. A domain run kind (`BuildRun`, `EpochRun`) describes that run under the same id and defines no second notion of an active run. |
| Step | `LoopStep` (is a `std-order` `Ordered`) | `BuildTask.step` | none; the phases are Python | yes | `std-loop`, unchanged |
| Requirement | `LoopRequirement`, `LoopCompletion`, `LoopGoal`, `LoopExpectation` | through `std-loop` | none | yes | `std-loop`, unchanged |
| Claim and lease | none | `BuildClaim`, `BuildClaimActivity`, lease rules in `claims.dl` | `journal_claim.py`, `git_claim.py` (Python only) | yes: one runner per run, one attempt per effect | `std-loop`: `LoopClaim`, `LoopClaimRenewal`, `claim_lease_ended`, `claim_held` (section 2.2) |
| Pending operation | `LoopPendingOperation {run, token}`, an input | `build_claim_release_pending` | `Attempt` records | yes | `std-loop`: `effect_pending`, derived from attempts and readbacks. `LoopPendingOperation` stays an input for recorded fixtures; no new adapter writes it. |
| Effect and receipt | `LoopSweepReceipt` closes a read; the effect contract has `EffectPlan`, `EffectApply`, `EffectState` | `BuildClaimDelete` and `BuildClaimRefRead`, settled in `claim_release.dl` | `Attempt`; `CleanupAttemptState` copies `EffectState` | yes: write, sign, distribute | `std-loop`: `LoopEffectPlan`, `LoopEffectAttempt`, `LoopEffectReadback`, the enum `LoopEffectState` with the contract's values, and `effect_*` relations (section 5) |
| Refusal | `LoopRefusal`, recorded only | none (`build_full_selection` is a selection outcome, not a refusal) | `dispatch` `conflicting_input`; Python raises | yes: every publication gate, and a step that refused its input | `std-loop`: `refusal` from `LoopRefusal` and from the new extensible `derived_refusal` (section 2.2) |
| Deadline | `LoopDeadline` (budget from a start observation) | the claim lease, computed apart in `claims.dl` | `cleanup-deadline` absolute `deadline_us` | yes: a run that never ends is stuck | `std-loop` `LoopDeadline`, with the absolute boundary of [standard packs everywhere](standard-packs-everywhere.md) once that lands. The lease ends by the same `until <= tick` comparison. |
| Observation sweep | `LoopSweep`, `LoopSweepReceipt`, `complete_sweep` | cites `LoopSweepReceipt` | `cleanup` `Sweep` with pages and coverage | yes: store and registry readbacks | `std-loop`. `cleanup`'s `Sweep` keeps its paging slots and names the `LoopSweepReceipt` that closes it. |

Step and requirement already have one home. Claim, lease, effect, receipt and refusal are defined twice today or would be once the engine epoch run defines them. They get one home in `std-loop`, which the [decision heads](decision-heads.md) give to the loop track. A new standard pack would split one model: a claim exists to make an effect single, a receipt settles an effect, a refusal makes a step stuck, and all of them close the same fixed point. `std-loop` keeps importing only `std-order`. A lease duration that a decision states stays in the pack that imports `std-decision` and reaches `std-loop` through an extension.

### 2.2 What `std-loop` gains

| Addition | Kind or relation | Derivation or slots |
| --- | --- | --- |
| Derived refusal | `// @extend .decl derived_refusal(run, step, reason)` | No clause in `std-loop`. `refusal(run, step, reason)` also holds for every `derived_refusal` row, so `structural_stuck`, `eligible` and the fixed point treat a derived refusal like a recorded one, with the importing pack's witness. |
| Effect plan | `LoopEffectPlan {id, run, step: LoopStep, reason}` | The exact planned input of one effect. Its `id` is the idempotency key: the plan hash of the effect contract. |
| Effect attempt | `LoopEffectAttempt {id, run, plan: LoopEffectPlan, sent_at: integer, outcome, source}` | One journaled attempt, as the effect adapter recorded it. `outcome` is `claimed` (the claim was made and no answer was recorded), `sent`, `refused` or `unknown`. |
| Effect readback | `LoopEffectReadback {id, run, plan: LoopEffectPlan, observed_at: integer, state, receipt: LoopSweepReceipt, source}` | A complete read of the effect's target after an attempt. `state` is `expected` (the target shows what the plan produces), `before` (it still shows the state before the effect) or `other` (it shows something else). It counts only with a receipt of its own run at its own tick. |
| Effect state | enum `LoopEffectState` | `planned`, `applying`, `unknown`, `applied`, `failed`, `cleaned`: the values of `EffectState` in the effect contract, declared once for packs. |
| Effect permission | `// @extend .decl effect_permitted(run, step, plan, reason)` | No clause in `std-loop`. The importing pack says why a planned effect may go out. |
| Claim | `LoopClaim {id, run, subject, generation, observed_at: integer, source}` | A claim observed at a cut: a branch ref, a write-once ref or a store object. |
| Claim renewal | `LoopClaimRenewal {id, claim: LoopClaim, generation, at: integer, source}` | One recorded push or renewal of a claim. |
| Lease budget | `// @extend .decl lease_budget(run, budget: number, reason)` | No clause in `std-loop`. The build pack derives it from its lease decision. A claim without a budget has no lease. |
| Lease and hold | `claim_lease_ended(run, claim, reason)`, `claim_held(run, claim, reason)` | The rules of `build/rules/claims.dl` without the pull-request reading: the latest renewal starts the lease, a tie or an unsourced latest renewal leaves it undecided, and the lease has ended at the cut when `start + budget <= tick`. |
| Effect relations | `effect_planned`, `effect_attempted`, `effect_pending`, `effect_confirmed`, `effect_discarded`, `effect_state` | Section 5. |

### 2.3 What moves, and how the build and provider packs import it afterwards

The moves land after this decision, each in its own pull request, never in this one.

1. **Claims.** `BuildClaimActivity` becomes `LoopClaimRenewal`. `BuildClaim` keeps `branch` and becomes a `LoopClaim` whose `subject` is the branch. The lease rules of `build/rules/claims.dl` move to `packs/std-loop/rules/claim.dl`. `BuildClaimLease` and the lease policy stay in the build pack, which supplies `lease_budget` from the decision in force on the policy date. `build_claim_release_plan` and `build_claim_held` stay build relations: they add the pull-request reading to `claim_held`.
2. **Effects.** `BuildClaimDelete` becomes a `LoopEffectAttempt` whose plan is the delete of one claim generation. `BuildClaimRefRead` becomes a `LoopEffectReadback`: `absent` is `expected`, `present` at the deleted generation or without one is `before`, and `present` at another generation is `other`. The settling rules of `build/rules/claim_release.dl` move to `packs/std-loop/rules/effect.dl`. `build_claim_released`, `build_claim_release_discarded` and `build_claim_release_pending` stay as build relations over `effect_confirmed`, `effect_discarded` and `effect_pending`, with the same rows.
3. **Provider effects.** `run/packs/cleanup-deadline` imports `std-loop`. Its `Attempt.state` ranges over `LoopEffectState`, and `CleanupAttemptState` goes. `run/packs/cleanup`'s `Attempt` becomes a `LoopEffectAttempt`, and its `Sweep` names the `LoopSweepReceipt` that closes it. `run/journal_claim.py` and `run/git_claim.py` stay as claim adapters; what they record is a `LoopClaim` without a lease.
4. **Pending operations.** `possible_progress` also holds while an `effect_pending` row names a plan of an unfinished step. `LoopPendingOperation` stays readable until no recorded fixture writes it.

A move that changes `std-loop` changes its hash. The same pull request re-pins every importer, the build pack among them, and keeps every build test green. The build pack's published relation names and rows do not change. Its consumers in CI read relations, not kinds, so selection, claims, the red list and the per-milestone progress keep working through the move. A build test whose records name a moved kind is restated by a planner on the `std-loop` kinds, with the same expectation, before the worker moves the rules. If a move cannot keep a published build row, it does not land. The build pack has no Python fallback: when its publication is missing or the checker refuses it, CI runs every suite, claims stay and nothing new starts, with a finding. No move may weaken that safe state; unknown never means less checking.

### 2.4 A run that buys work from a provider

The build run is a paid run whose provider is an LLM provider. The engine epoch run buys compute: CI runners and the disposable cluster. The paid run buys servers from a hosting provider. All three order work, claim it so that it is done once, take delivery, accept it against independent evidence, pay for it within a decided bound, and clean up what is left. `run/packs/` already holds most of that layer in a provider-neutral form; only `provider-terms` names a provider.

| Stage | Paid run (servers) | Build run (LLM work) | Engine epoch run (compute) |
| --- | --- | --- | --- |
| Order | one order of the approved plan; `dispatch` binds the approval and its cap to the exact plan hash ([price enforcement](run-price-enforcement.md)) | start a worker session on one red test | dispatch the compile, evaluation and check jobs, and the Feldera shards |
| Claim | `refs/rezono/run-claims/<plan hash>`, created once with an empty lease ([shared claim](run-shared-claim.md)) | `refs/heads/task/<test>`, created once with an empty lease ([worker card](../WORKER.md), step 2) | `effect:<plan>` and `run:<run>` (section 5) |
| Delivery | the machines that come back, with addresses and disks (`cluster-shape`) | the pull request with the lifted mark | the evaluated rows and witnesses, then the written forms |
| Acceptance | the delivered machines match the order and the plan (`cluster-shape` `valid_machine`, order status, price enforcement) | the red test turns green and the checker agrees: the required checks pass, then the merge queue | `publish_allowed` (section 3.3) |
| Payment | rated and billed charges against an approved ceiling (`invoice-drift`, [run reconciliation](run-reconciliation.md)) | tokens and run minutes, usage-billed, today without a cap | CI and cluster minutes, today without a cap |
| Cleanup | a complete tagged-resource inventory confirms cleanup (`cleanup`), before a deadline (`cleanup-deadline`, [server deadline](run-server-deadline.md)) | release an expired claim, confirmed by a complete ref read (`build_claim_release_*`, `scripts/release_claims.py`) | tear down the cluster and pipelines, confirmed by a complete read |

Four concepts are defined twice today, once for servers and once for LLM work.

- **Claims.** [Shared claim](run-shared-claim.md) creates `refs/rezono/run-claims/<plan hash>` with `--force-with-lease=<ref>:`, which succeeds once. The worker card claims `refs/heads/task/<test>` with the same empty lease. `scripts/release_claims.py` releases it with `--force-with-lease=<ref>:<head>`, and the build pack models that release (`build/rules/claim_release.dl`). They are one mechanism, a write-once ref. They differ only in what is claimed (a plan hash or a red test) and whether a lease ends the claim: a server claim is never released, a task claim is. `scripts/release_claims.py` also writes the lease as a literal four hours, while the build pack reads it from `BuildClaimLease` and its decision. That literal is a decision in code, fate (c) of [code does not decide](code-does-not-decide.md).
- **Brake and lease.** Two kinds of decided bound appear in both runs.
  - *How much work at once.* For servers, `cluster-shape`'s `Line.quantity` bounds the order. For LLM work, `BuildQueueLimit` bounds the planner slots.
  - *How long a phase may take.* For servers, `probe-profiles`' `ProbePhaseBudget` (seconds, under a `std-decision` `Decision`) bounds a phase. For LLM work, `BuildClaimLease` (seconds, under a `Decision`) bounds a claim.
  - Both are a decided bound on work bought from a provider. The time bound is a `LoopDeadline` whose budget a decision states (section 2.2, `lease_budget`).
- **Ports.** [Provider ports](run-provider-ports.md) names a price and availability read, a single order, order status, a tagged-resource inventory and cleanup. It also requires a complete, independent inventory before cleanup counts. The build run has the same ports: a quota or price read of the LLM provider, starting a worker, the status of a session and its pull request, an inventory of `task/` branches and sessions, and release. It has the same rule too: a complete ref read with its receipt confirms a release (`BuildClaimRefRead`).
- **Billing.** `provider-terms` derives that an order with a usage-billed detail (`UsageDetailType`) has no quote guarantee. An LLM session is billed by usage, so the same rule applies: its price is never guaranteed. Like a paid order, it needs an approved cap, a `std-decision` ceiling as in [run reconciliation](run-reconciliation.md), against which its rated usage is compared. The build run has no such cap today, and neither has the engine epoch run's compute.

**The target.** The provider layer gets one home: a standard pack for runs that buy work. It is built from the provider-neutral parts of `run/packs/` (`dispatch`, `cleanup`, `cleanup-deadline` and the reconciliation of `invoice-drift`) and sits on `std-loop` and `std-decision`. Each run then supplies only its provider: the paid run through `provider-terms` and its ports; the build run through an LLM provider's terms, its claims as provider claims and its sessions as orders; the engine epoch run through its compute. The build run's mapping is the row of the table above. Its migration is not part of this decision. The owner may make it a steering point of its own; until then the build pack and `run/packs/` stay as they are. The pack's name is registered as [standard pack names](standard-pack-names.md) requires when the decision that creates it lands.

## 3. The engine epoch run

### 3.1 Steps and gates

The run is orchestration only. Each step runs a component that exists today. The loop orders the steps, holds their gates, and records their verdicts; it never evaluates the epoch itself.

| Step | Completion token | What runs | Gate |
| --- | --- | --- | --- |
| `compile` | `compiled` | the compiler at the judged commit | the run's claim |
| `evaluate-duckdb` | `evaluated-duckdb` | the batch backend | `compiled` |
| `evaluate-feldera` | `evaluated-feldera` | the Feldera pipeline | `compiled` |
| `compare-engines` | `engines-agree` | the engine comparison over rows and witnesses | both evaluations |
| `check` | `checked` | the independent checker and the publication plan: witnesses (R7, per role), access, publication requirements, assets, sources, evidence and surface. Nothing is written. | `engines-agree` |
| `write-forms` | `forms-written` | the publisher's write: objects, views, forms, then the manifest and its head | `checked`, no derived refusal, `publish_allowed` for every role (section 5) |
| `sign-<role>` | `signed-<role>` | the signing effect over the role's statement | `forms-written`, `publish_allowed` for that role |
| `distribute-<role>` | `distributed-<role>` | the push of the sealed form with its statement and signature as a referrer | `signed-<role>` |

Each step is a `LoopStep`. Precedence comes from `std-order`, so every step requires its predecessor's completion token. The plan's records (steps, completions, expectations, required checks and accepted formats) are facts of the epoch pack in `epoch/facts/`. For each filtered role of the deploy profile, the input adapter adds one `sign-<role>` and one `distribute-<role>` step. It reads those roles from the profile, and an `EpochRoleStep` row ties each step to its role. A step's adapter records its completion token only after a complete readback of what the step produced, under the step's `LoopSweepReceipt`. A run has one `LoopDeadline` on each `distribute-<role>`. Its budget is a plan fact, so a run that never ends is stuck, not pending.

### 3.2 Kinds of the epoch pack

The pack lives in `epoch/` with the name `engine-epoch`, beside `build/`, and imports `std-loop`. Its kinds hold what each step observed. A kind marked *complete only* is read by the complete role alone (section 3.5).

| Kind | Slots | Independent origin and acceptance question |
| --- | --- | --- |
| `EpochRun` | `id`, `pack`, `epoch: integer`, `commit`, `profile` | The protected caller that starts the run. Which epoch of which pack, from which source commit and deploy profile, does this run take to distribution? `id` is the run's `LoopActiveRun` id. |
| `EpochRole` | `id`, `run`, `name` | The deploy profile. Which filtered roles get a form, a statement and a distribution? |
| `EpochRoleStep` | `id`, `run`, `step: LoopStep`, `role: EpochRole`, `stage` (`sign`, `distribute`) | The input adapter. Which per-role step serves which role? |
| `EpochEnginePin` | `id`, `run`, `version`, `wheel_sha256`, `commit` | `epoch/engine-pin.yaml` at protected main, held to the registry's digest. Which released engine evaluates this run's loop? |
| `EpochTool` | `id`, `run`, `step: LoopStep`, `tool`, `version`, `sha256` | The step's adapter, from the build record the step ran with. Which compiler, engine, checker, publisher or signer ran this step? |
| `EpochDefinition` | `id`, `run`, `definition_sha256`, `compiler_sha256` | The compile step. Which pack definition was compiled, by which compiler? |
| `EpochSurface` | `id`, `run`, `against`, `class` (`patch`, `minor`, `major`), `before_major`, `before_minor`, `before_patch`, `after_major`, `after_minor`, `after_patch` (integers) | The check step, from `surface.compatibility`. Against which earlier main manifest was the public surface compared, how far did it change, and which pack versions do the two bundles name? |
| `EpochCheck` | `id`, `run`, `step: LoopStep`, `check`, `outcome` (`green`, `red`, `unknown`), `violations: integer`, `source` | The step's adapter, copying the verdict of the engine, the comparison or the checker. What did this check find for the whole run? |
| `EpochRoleCheck` | `id`, `run`, `step: LoopStep`, `role: EpochRole`, `check`, `outcome`, `violations: integer`, `source` | The same, for one role. |
| `EpochRequiredCheck` | `id`, `step: LoopStep`, `check`, `scope` (`run`, `role`) | A plan fact. Which checks must have a verdict once their step is done? |
| `EpochRoleForm` | `id`, `run`, `role: EpochRole`, `snapshots_sha256`, `sources_sha256`, `objects_sha256` | The check step's publication plan, before anything is written. Which bytes would this role's form hold? |
| `EpochPackFacts` | `id`, `run`, `pack_sha256` | *Complete only.* The compile step. Which pack bytes, facts included, were compiled? |
| `EpochSource` | `id`, `run`, `source`, `position` | *Complete only.* Where each source stood. |
| `EpochCheckDetail` | `id`, `check`, `first`, `report_sha256` | *Complete only.* The first error and the digest of the full report of a check. |

An adapter copies a verdict; it does not judge it. The checker stays the code that finds a proof error, and the publication plan stays the code that computes the objects. Two paths lead from a step to a refusal, one per fate of section 3.4:

- **Input integrity, fate (d).** The code that reads the input keeps its check and raises as today. The step's adapter records the raise as a `LoopRefusal` of its step, with the check's name (such as `rezono:assets`) as the reason. That is an observation of the step, not a judgement, and the recorded refusal makes the step stuck.
- **Publication gate, fate (c).** The code that computes the verdict returns it instead of raising. The adapter records it as an `EpochCheck` or `EpochRoleCheck`, and the rules below refuse.

A step that neither completes nor records anything leaves its token unknown. Its successors wait, and the deadline makes the run stuck. Nothing is published, and there is no other path to publish by.

### 3.3 Relations of the epoch pack

| Relation | Derivation |
| --- | --- |
| `derived_refusal(run, "write-forms", reason)` | One clause per gate of fate (c) below. Every derived refusal lands on `write-forms`, so one red finding writes nothing, as today. A refusal that needs a step's result waits until that step is `done`; it never refuses ahead of its evidence. |
| `publish_allowed(run, epoch, role, reason)` | For an `EpochRole` of an `EpochRun`, with `epoch` the run's epoch and `role` the role's `name`: `done` of `compile`, `evaluate-duckdb`, `evaluate-feldera`, `compare-engines` and `check`; the `EpochTool` of each of those steps; the `EpochEnginePin`; the `EpochDefinition`; the role's `EpochRoleForm`; the role's green `rezono:proofs` and `rezono:access` checks; and no `refusal` in the run, recorded or derived. `reason` is the `EpochRoleForm` id. Every gate and every pin is a positive premise, so the witness cites each one. A check that a pack may lack, such as assets, is covered by the absence of a refusal, which the witness carries as a negative premise. |
| `epoch_allowed(run, epoch, reason)` | The complete counterpart, one row per `EpochSource` of the run with that source as `reason`: the source, the `EpochPackFacts`, and no role of the run without a `publish_allowed` row. It goes into the complete manifest only, never into a statement. |
| `effect_permitted(run, step, plan, reason)` | `write-forms`: a `LoopEffectPlan` of the step and `publish_allowed` for every role of the run. `sign-<role>` and `distribute-<role>`: a plan of the step and `publish_allowed` for its role. |

### 3.4 One fate per publisher check

The fates are those of [code does not decide](code-does-not-decide.md), section 1. An input-integrity check asks whether the input can be read as what it claims to be: a file is there and has its format, an asset or a source is listed, a witness has the shape of a witness. Reading input is what code may do, so these checks keep fate (d). A publication gate asks whether a well-formed epoch may be published: the engines agree, a proof exists and the checker accepted it, each role reads what its form says. These are fate (c): the code that computes the verdict stays the reader, and the decision moves into the epoch pack, where `publish_allowed` can cite it. No check gets fate (a) or (b): none is unused, and none duplicates a rule.

| Check in `publish.py` today | Kind | Fate | Afterwards |
| --- | --- | --- | --- |
| `instance_pack`: the theory flag is not a boolean | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `instance_pack`: a theory pack publishes no instance | input integrity: a theory epoch is not an instance to publish | (d) | stays; `LoopRefusal` of `check` |
| `rule_ir`: no rule definitions, not JSON, not `rezono.rules/1`, or the checker cannot load it | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `calc_ir`: calculation witnesses without `ir/calc.json`, not JSON, or not `rezono.calc-ir/1` | input integrity | (d) | stays; `LoopRefusal` of `check` |
| malformed witness instances (`shaped`) | input integrity | (d) | stays; `LoopRefusal` of `check` |
| relations no definition accounts for | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `verify`: the checker refuses the calculation bindings or the seals, or a sealed kind has no seal | input integrity of the compiled program | (d) | stays; `LoopRefusal` of `check` |
| `metadata_checked`: the loaded check metadata is not the bundle's | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `rezono:sources`: stale fact sources, a role's source entries, the source sets | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `rezono:assets`: an image cell names an unlisted file, or the asset check fails | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `rezono:evidence`: admission refuses the evidence | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `check_publication_requirements`: malformed requirements | input integrity | (d) | stays; `LoopRefusal` of `check` |
| `_surface_refusal`: a broken head, a missing or mismatched bundle, a malformed version | input integrity | (d) | stays; `LoopRefusal` of `check` |
| red engine checks (`e.checks`) | gate: the engine's own checks found violations | (c) | `EpochCheck` of the evaluate step; the pack refuses |
| `checked`: the checker finds errors in the proofs, complete and per role (R7) | gate: a proof exists and the checker accepted it | (c) | `EpochCheck` and `EpochRoleCheck` `rezono:proofs`; the pack refuses |
| `access.Uncovered` | gate: access per role | (c) | `EpochRoleCheck` `rezono:access`; the pack refuses |
| `check_publication_requirements`: a required conclusion has no unique readable proof | gate: the role gets what it must | (c) | `EpochRoleCheck` `publication_required`; the pack refuses |
| `_surface_refusal`: R033 and the version that does not move far enough | gate: the public surface may change this way | (c) | `EpochSurface`; the pack refuses, by [surface compatibility](language-surface-compatibility.md) section 4 |
| engine disagreement (new) | gate: the engines agree | (c) | `EpochCheck` `rezono:engines` of `compare-engines`; the pack refuses |
| a required verdict that never came (new) | gate: unknown is not green | (c) | `EpochRequiredCheck` with its step done and no row; the pack refuses |

A gate verdict refuses when its outcome is `red` or `unknown`, or when it is `green` with violations above zero. The surface gate refuses only when the earlier version's major is 1 or more. It refuses a `major` class with R033, since no accepted proposal is modelled yet. It also refuses a version that moves less than the class: a `major` change needs a higher major, a `minor` change a higher major or, at the same major, a higher minor, and a `patch` change any higher version. The refusal's reason row is the culprit record: the check, the required check or the surface row.

**The audit.** The audit at `8d1fa9c` found the publisher in line, and every row above that existed then keeps that reading. Each such check reads input, or stops on the independent checker's verdict. What moves is only the step from verdict to "not published", because `publish_allowed` must now carry it as a witness. The one exception postdates the audit. `surface.py` came with pull request 1208 (`fa51710a`) and `_surface_refusal` with pull request 1244 (`4ac7e665`); neither is an ancestor of `8d1fa9c`, and no other check in `publish.py` changed since. `surface.refusal` decides by a policy: whether the earlier pack version is 1.0.0 or later, whether a change class is refused, and how far the version must move. That is a decision in code, so its policy goes to fate (c). Its comparison of two bundles (`surface.compatibility`) stays the reader, fate (d).

### 3.5 What a role's witness may cite

An epoch statement depends on nothing its role may not read, and two worlds a role cannot tell apart give it the same statement. The witness behind the statement holds to the same rule. A premise of `publish_allowed` for a role is a row whose bytes are equal in two such worlds:

- gate observations carry the step and run as their reason, never a digest over rows;
- the pack is cited by `definition_sha256` and `compiler_sha256`, which do not change when a fact changes;
- the role's own snapshots, source set and form objects are cited by the hashes in its `EpochRoleForm`;
- tool and engine pins are versions and digests of code.

`pack_sha256`, source positions, comparison and checker report digests and first errors are complete only. Only `epoch_allowed` cites them. This is why the role's witness cites the pack by its definition and its own sources, while the complete witness cites the pack hash and every source position. The read rules of the epoch pack give a role its own `publish_allowed` row and the premises of that row's witness, and nothing else.

## 4. The statement names why it exists

Version 3 of the epoch statement (`predicateType` `https://rezono.org/epoch-statement/v3`, `format` `rezono.epoch-statement/3`) keeps every field of version 2, including `previous` and `diff` both or neither, and adds one field to `EpochPredicate`:

| Field | Type | Present | Value |
| --- | --- | --- | --- |
| `allowed` | `Sha256` | always in version 3 | the SHA-256 of the role's `allowed.json` bytes |

- **`allowed.json`** is an object of the role's form, in canonical JSON, with the members `format` (`rezono.epoch-allowed/1`), `relation` (`publish_allowed`), `row` (the proved row: run, epoch, role, reason), `proof` (the chosen proof of that row, `contracts/proof.yaml`), `rows` (the base rows its witnesses cite, by relation), `definition` (the epoch pack's `definition_sha256`), `rules` (the SHA-256 of the epoch pack's rule IR) and `engine` (the `EpochEnginePin`: version, wheel SHA-256 and commit). The checker checks the proof against those rows and that rule IR, as it checks any role's proofs.
- **Subject agreement.** `allowed.json` is in `subject` with a digest equal to `predicate.allowed`, as `diff.json` is for `predicate.diff`.
- **The verifier** (`rezono_publication.statement.verify`) reads versions 1, 2 and 3. For version 3 it requires `allowed`, holds it to the subject's digest, and requires the proved `row` to name the statement's role and epoch; a problem it finds names `allowed`. `rezono_publication.statement` names the object `ALLOWED = "allowed.json"`. A form that holds it gets a version 3 statement from `make`, which may refuse a proof of another role or epoch at once with a `ValueError` that names `allowed`. A form without one still gets version 1, or version 2 once that is built.
- **Why a flat hash.** `previous` and `diff` are flat SHA-256 fields of the predicate, each naming one object by its bytes. `allowed` is the same shape, so the chain and the permission compose: a role's chain of statements is also a chain of the proofs of why each one exists. Version 3 follows version 2 and changes none of its rules.
- **No cycle.** `allowed.json` cites the role's planned object hashes (`EpochRoleForm`) taken before anything is written. Those hashes exclude `allowed.json` and `statement.json`, so the statement can name the proof, and the proof does not name the statement.

## 5. Effects exactly once

Writing, signing and distributing are effects. Each goes through the effect contract's plan, attempt and readback, and is idempotent on retry: a retry reads the target again and never repeats an attempt.

| Relation | Derivation |
| --- | --- |
| `effect_attempted(run, plan)` | Any `LoopEffectAttempt` of the plan in the run with a source, whatever its outcome. An attempt consumes its key. |
| `effect_planned(run, step, plan, reason)` | `unblocked(run, step, _)`, `effect_permitted(run, step, plan, reason)` and not `effect_attempted(run, plan)`. The effect port applies only these rows. |
| `effect_confirmed(run, plan, reason)` | The first settling readback after an effective attempt (`claimed`, `sent` or `unknown`) has state `expected`. A settling readback has state `expected` or `other`, is later than the attempt and has a receipt of its own run and tick; a readback that shows `before` settles nothing. |
| `effect_discarded(run, plan, reason)` | The first settling readback has state `other`, or the only attempt was `refused`. |
| `effect_pending(run, plan, reason)` | An effective attempt with no settling readback yet: `still-before` when a later readback shows `before`, else `readback-missing`. It keeps the fixed point open. |
| `effect_state(run, plan, state, reason)` | The contract's journal state, derived: `planned` from `effect_planned`, `applying` from a `claimed` attempt, `unknown` from `effect_pending` otherwise, `applied` from `effect_confirmed`, and `failed` from `effect_discarded`. `cleaned` comes from the confirmation of the plan's own cleanup plan, which a later decision names. |

The engine epoch's keys are the SHA-256 of the manifest bytes for `write-forms`, of the role's statement bytes for `sign-<role>`, and of the seal digest with the statement's SHA-256 for `distribute-<role>`. The adapter that computes a key records its `LoopEffectPlan`. Before it sends, the effect adapter makes a `LoopClaim` on the subject `effect:<plan>` without a lease: a conditional create in the publication store, the write-once claim of the [shared claim](run-shared-claim.md). It records the attempt as `claimed`, and then its answer. A crash after the claim leaves `claimed`, which the readback settles. Two runners therefore send at most once per key, which is `AtMostOneSubmit` of the [Effect](../formal/Effect.tla) model. The settling order is that of [Claims](../formal/Claims.tla). A run is driven by one runner at a time through a `LoopClaim` on `run:<run>` with a lease from the epoch pack's lease decision. When the lease ends, another runner resumes the same run id, and the effect claims keep each effect single.

## 6. Executor: a pinned earlier engine evaluates the loop

The [loop executor](../loop/executor.py) runs the rounds: it evaluates the epoch pack, applies the `effect_planned` rows and the step commands of `unblocked` steps, sweeps, records, and evaluates again. The engine that evaluates the epoch pack is a released one. `epoch/engine-pin.yaml` names its `version`, the `wheel_sha256` of the released wheel and the `commit` of its `v<version>` tag. The version is lower than the version in `rezono/package.json` at the judged commit, so the engine that judges a commit is never that commit's engine. This is stage-0 bootstrapping: the released engine runs the loop, and the engine under change computes only the epoch the loop judges. The executor installs the pinned wheel by hash in an environment of its own and records it as `EpochEnginePin`.

Bumping the pin is a pull request that changes `epoch/engine-pin.yaml` and nothing else. Its check replays the recorded epoch runs of the last released version with the new pin; a row that differs is a finding, repaired against the semantics before the bump lands.

## 7. The checker stays independent

The `check` step runs `checker/` as today. The loop records the checker's verdicts; it does not check witnesses and does not replace the checker. The loop's own conclusions get a proof that the same independent checker checks: `allowed.json` against its rows and the epoch pack's rule IR, and the epoch pack's publication like any other pack's.

## 8. Sealing later

Sealing a round as certified with Feldera is out of scope. The hook is a step `seal` that every `distribute-<role>` precedes, and `std-loop`'s existing certified-round relations (`verified_round`, [safe step rounds](safe-step-rounds.md), [loop certificate admission](loop-certificate-admission.md)). No relation of this decision depends on a seal, and no seal is designed here.

## 9. Transition

There is no fallback and no period in which two paths decide. A missing or refused gate means the epoch is not published.

1. **Vocabulary first.** `std-loop` gains the kinds and relations of section 2.2. Each move of section 2.3 follows with its re-pin and its restated tests, and the build pack's publication stays the same throughout.
2. **The epoch pack.** The pack, its adapters and the red tests of section 10 land. Until the switch in step 3, publication runs as it does today. That is the state before the switch, not a fallback beside it.
3. **One switch.** One pull request lets the epoch run drive publication. It lands once the red tests of section 10 are green and a released engine exists to pin. From then on there is one path. If the epoch pack's evaluation is missing, the checker refuses the epoch pack's publication, or a gate is missing, refused or unknown, nothing is published and the run reports the finding. The same pull request removes the gate raises of fate (c) from `publish.plan`, which then returns those verdicts. It deletes the Python sequence that the run replaces (fate (a)), or moves it under `tests/` as an oracle of the epoch pack (fate (b)). The input-integrity checks of fate (d) stay where they are.
4. **Statement version 3** lands after version 2. Until the switch, a form has no `allowed.json`, and statements stay at version 1 or 2.

No released engine exists at this decision: `rezono/package.json` names `0.1.0` and no `v` tag exists. The pin, and with it step 3, waits for the first release.

## 10. Red tests

All are `extra:`. Release 1 does not include this run.

| Test | Pins |
| --- | --- |
| `loop/tests/test_shared_run_vocabulary.py::test_effects_and_claims_are_declared_once` | the `std-loop` kinds of section 2.2, and no copy of the effect states in a run pack |
| `loop/tests/test_shared_run_vocabulary.py::test_build_claims_use_the_shared_kinds` | moves 1 and 2 of section 2.3 (waits for the planner restating the claim tests) |
| `loop/tests/test_shared_run_vocabulary.py::test_a_derived_refusal_makes_its_step_stuck` | `derived_refusal` |
| `loop/tests/test_shared_run_vocabulary.py::test_an_effect_is_attempted_once_per_plan` | the `effect_*` relations of section 5 |
| `loop/tests/test_engine_epoch.py::test_publish_allowed_cites_every_gate_and_pin` | section 3.3, `publish_allowed` and `effect_permitted` |
| `loop/tests/test_engine_epoch.py::test_publication_gates_are_derived_refusals` | the gates of fate (c) in section 3.4, and a recorded refusal of fate (d) |
| `loop/tests/test_engine_epoch.py::test_a_role_witness_ignores_complete_only_rows` | section 3.5 |
| `loop/tests/test_engine_epoch.py::test_the_loop_engine_is_an_earlier_release` | section 6 |
| `publication/tests/test_statement_allowed.py::test_the_statement_names_why_it_exists` | section 4 |

## Alternatives

- **Keep the Python sequence and log its reasons.** A log line is not a relation: no witness, no checker, and nothing a statement can name.
- **Evaluate the loop with the engine of the judged commit.** A broken engine would then judge itself. A pinned release keeps the judge outside the change.
- **Let the loop check the witnesses.** That would make the loop a second checker with the engine's code paths. The checker stays the independent oracle (root AGENTS.md, rule 6).
- **Name `pack_sha256` in the role's witness.** It hashes facts the role may not read, so the statement would differ between worlds the role cannot tell apart. The complete witness carries it instead.
- **A new standard pack for claims and effects.** Claims, receipts, refusals and the fixed point are one model; a second pack would make `std-loop` import it for every run. The provider layer of section 2.4 is a different cut: order, delivery, acceptance, payment and cleanup are what a run buys, not how a loop proceeds, so it sits on `std-loop` and not in it.
- **Keep the build run as a kind of its own.** Its claims, lease, queue bound, ports and missing cap are the paid run's under other names (section 2.4). Two definitions would drift, as the literal four hours in `scripts/release_claims.py` already has from `BuildClaimLease`.
- **Add `allowed` to version 2.** Version 2 is specified and its test exists; changing its fields before it is built would move a target under a worker. Version 3 extends it without touching its rules.
