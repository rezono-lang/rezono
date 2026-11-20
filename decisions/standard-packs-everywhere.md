---
decider: [owner]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: standard-packs
---

# Use the standard packs wherever they fit, and retire the variants that grew beside them

The [vision](../docs/vision.md#rules-not-scripts) says that a standard pack (`packs/std-*`) is used wherever it fits, and that an example does not grow its own variant. An audit at commit `8d1fa9c` found two places where that does not hold, and a few smaller ones. A day-number stopgap that starts inside `std-decision` has spread to the packs that import it, and the reference platform models its safe steps in a schema and a rule file of its own beside `std-loop`, which it imports but feeds no rows. Rules can now read a date, so the owner adopted, on 20-11-2026, the advice to make the standard packs consistent now. This decision says, per case, what changes, in which order, and which red test marks each step. [Day numbers in rules](rule-day-numbers.md) · [Safe transition rounds](safe-step-rounds.md) · [Certificates at the batch boundary](loop-certificate-admission.md) · [Five scenes](platform-five-scenes.md) · [Decision heads](decision-heads.md)

## 1. Day numbers give way to dates

### 1.1 What is there

[`packs/std-decision/schema/decision.yaml`](../packs/std-decision/schema/decision.yaml) keeps `valid_from_day` and `valid_until_day` beside `valid_from` and `valid_until`: the date as a whole number `YYYYMMDD`, "because rules cannot read a date yet". Four schema rules make each date and its number come together, [`rules/decision.dl`](../packs/std-decision/rules/decision.dl) reads only the numbers, and `ReferenceDate` has only a number, `day`. The same stopgap is copied elsewhere:

| Where | Day numbers |
| --- | --- |
| `examples/subsidy/schema/credentials.yaml` | `TrustEntry.valid_from_day`, `valid_until_day`; `Credential.issued_on_day`; `IdentityStatement.issued_on_day`; `StatusLookup.looked_up_on_day`. `rules/credentials.dl` reads them, `facts/credentials.yaml` writes them. |
| `examples/subsidy/views.yaml` | `EvaluationDay`, a `ReferenceDate`, is read by `std-time` with `reading: yyyymmdd`, while the scheme parameters are read from their dates with `reading: days`. |
| `packs/std-review/schema/review.yaml` | `Review.day`, `RoleGrant.from_day`, `RoleGrant.until_day`, "as in `std-decision`" ([review and rights](review-and-rights.md)). |
| `build/rules/policy_date.dl` | reads `reference_date__day` and rebuilds a calendar date from a tick to compare with it. |
| `run/packs/probe-profiles/rules/budgets.dl` | orders reference dates by `reference_date__day`. |
| `loop/build_decision_capture.py` | writes each decision head's days also as `*_day` numbers ([decision heads](decision-heads.md), section 4). |
| `examples/platform` | `Release.released_on_day` and `SupportQuery.as_of_day`, numbers of the platform's own, and the `std-decision` rows of the five scenes. |

The [day-number decision](rule-day-numbers.md) rejects a precomputed day-number fact: it copies the date into a second fact with no link to the first. The roadmap page that the schema's description points to for the open question no longer exists.

### 1.2 How a rule reads a date

A rule compares two dates in their native order. In a `.dl` rule both sides are variables that positive literals bind to native `date` columns:

```prolog
took_effect(d, r) :- decision(d), reference_date__date(r, on), decision__valid_from(d, from), from <= on,
    !decision__state(d, "proposed").
```

Today the reader refuses a `date` table, and an order comparison takes whole numbers only. The [date equality decision](independent-date-equality.md) admits `date` columns in the rule IR and equality between two of them; its red test, `compiler/tests/test_recorded_dates.py::test_independent_date_equality`, comes first. This step extends it to `<`, `<=`, `>` and `>=` between two `date` variables. Both SQL engines compare `DATE` values, the Soufflé helper compares a date by its day number, and the checker compares the two dates of the witness, so the proof ends in the dates as recorded. A text or a number cannot stand in for a date, and no date literal comes in. `rezono 1` reads `Date` directly and compares two `Date` values with the same operators, which lower to the same comparison, so the staged Rezono candidate of `std-decision` and its Datalog form keep one meaning.

`@days` stays for day arithmetic, where a number of days is needed: a horizon in days, or a tick read as a day, as in the build pack's policy date. For that it also takes a variable bound to a `date` column, and lowers to the `days` assignment that a view with `reading: days` already produces (`compiler/rezono_compiler/view_rules.py`). A plain comparison of two dates never goes through it.

### 1.3 `std-decision` after the change

- The rules read `valid_from`, `valid_until` and a new slot `ReferenceDate.date` (`Date`, required). The window stays half-open: a decision applies from `valid_from` and no longer on `valid_until`. Time still comes from the dates and `supersedes`, never from the state.
- The four schema rules that tie a date to its number go. `valid_from_day`, `valid_until_day` and `ReferenceDate.day` stay for one step as optional slots that no rule reads, with a description that says they are retiring (a deprecated slot cannot be spelled yet, [language deprecation](language-deprecation.md)), and then go.
- `EvaluationDay` of the subsidy scheme, a `ReferenceDate`, inherits `date`, and `std-time` reads it with `reading: days`, as it reads the scheme parameters.

### 1.4 Migration order

Every pack that imports `std-decision` pins it by the hash of its definition files (`pack_hash` in `compiler/rezono_compiler/modules.py`), and the compiler refuses a pin that does not match. So each step that changes `std-decision` re-pins, in the same pull request, the `sha256` of its import in each of `build/pack.yaml`, `examples/platform/pack.yaml`, `examples/subsidy/pack.yaml`, `examples/subsidy-scheme/pack.yaml`, `run/packs/invoice-drift/pack.yaml`, `run/packs/offer-selection/pack.yaml` and `run/packs/probe-profiles/pack.yaml`. No fixture pack imports `std-decision`.

1. **Compiler.** Order comparisons between two `date` variables, on top of date equality, and `@days` on a `date` column for day arithmetic (section 1.2). They are part of the task of step 3, which names them.
2. **Planner: both spellings.** `std-decision` gains `ReferenceDate.date` as an optional slot, and its importers are re-pinned. Every test, oracle and fact file that writes `std-decision` rows or reads their numbers then writes the dates beside the numbers, and an independent oracle reads the dates. Decision rows already carry both, because the schema requires them together; raw table rows and reference dates do not. The tests are `compiler/tests/test_std_decision.py`, `compiler/tests/rezono/test_whole_std_decision.py`, `examples/platform/test_five_scenes.py`, `examples/platform/proof_cases/test_decision_standing.py`, `test_network_policy_provenance.py`, `test_norm_standing.py`, `test_successor_window.py` and `test_support_version_policy.py`, `examples/subsidy/test_subsidy.py` and `test_local_suppose.py`, `loop/tests/test_build_claim_release_plan.py`, `test_build_decision_capture.py`, `test_build_decision_rules.py` and `test_build_task_order.py`, and `run/tests/test_physical_nested_allocation.py`, `test_probe_profile_budgets.py` and `test_run_reconciliation.py`. A worker cannot change them, and a pull request that lifts a mark changes nothing else that is protected, so this comes first.
3. **`std-decision` reads dates** (red test A). Its rules, its staged candidate and its README read the dates as in section 1.3; the build pack's `policy_date.dl` reads `reference_date__date` through `@days`, because it compares the date with a tick, and probe-profiles' `budgets.dl` orders reference dates by `reference_date__date`; the importers are re-pinned.
4. **Subsidy** (red test B). The credentials schema loses its `*_day` slots, `rules/credentials.dl` compares the dates in their native order, the facts drop the numbers, and `views.yaml` reads `EvaluationDay.date` with `reading: days`. The subsidy scheme follows where it shares the kinds.
5. **Every other consumer**, each in its own pull request after the planner has prepared its tests as in step 2: the platform (`released_on_day`, `as_of_day` and its `std-decision` rows), `std-review` (`Review.day`, `RoleGrant.from_day`, `until_day`), the build capture adapter, which stops writing `*_day`, and the run packs.
6. **Contract.** `std-decision` removes `valid_from_day`, `valid_until_day` and `ReferenceDate.day`, and every importer is re-pinned. This is a planner pull request that lifts no mark, so it may also remove the numbers from the remaining test rows, among them the `valid_from_day` check of `test_scene_decisions_are_std_decision_facts`, which is right until this step.

`std-decision` moves from 0.1.1 to 0.2.0 in step 3 and to 0.3.0 in step 6.

## 2. The platform's safe steps are `std-loop` rows

### 2.1 What is there

`examples/platform/schema/safe_step.yaml` declares a cut, a requested step, an observation and a scope receipt, and `examples/platform/rules/safe_step.dl` derives `startup_transition_result` from them: which cut counts, which observation is current, when two readings contradict, which receipt covers a scope, and a verdict with a reason. `std-loop` already has each of these, and its rules carry the round of [safe transition rounds](safe-step-rounds.md) and the authority rules of [certificates at the batch boundary](loop-certificate-admission.md). The platform imports `std-loop` since commit `7cd8d66` (section 3 of [five scenes](platform-five-scenes.md)), but no `std-loop` row reaches its facts. The restore trial does the same in [`rules/restore_offline.dl`](../examples/platform/rules/restore_offline.dl): its dependency readings are observations of a run, judged by rules of its own.

### 2.2 Each kind and its counterpart

| `safe_step.yaml` | `std-loop` |
| --- | --- |
| `SafeRoundCut` (a cut of a run) | `LoopSweepReceipt` (`id` = the cut, `run`, `event_time`) for an active run (`LoopActiveRun`). The current cut is `step_safety_current_cut`: one receipt with the latest time, and equal times leave it undecided. |
| `SafeStepRequest` (run, effect, subject) | `LoopStep`, with its order from `std-order`, and one `LoopRequirement` per token the step needs in the run. What the step changes (`effect`, `subject`) is the pack's match and identity ([safe transition rounds](safe-step-rounds.md), section 1) and stays the platform's: a kind of its own that is a `LoopStep`, not a request kind beside it. |
| `SafeStepObservation` (run, cut, subject, attribute, value) | `LoopObservation` (`run`, `token` naming the subject and the attribute, `event_time`, `state`, `value`, `reason` = the evidence, `scope` = the reader, `sweep` = the cut), and `LoopExpectation` for the value a step needs. |
| `SafeStepScope` (run, cut, reader, scope) | The completeness receipt of [scoped completeness](scoped-completeness.md), admitted at the cut and read through `complete_sweep` (collector = the reader, window = the cut). An absence over observed data follows only from it, as `current(run, token, "absent", …)`. |

| `safe_step.dl` | `std-loop` |
| --- | --- |
| `safe_step_cut` | `step_safety_current_cut` |
| `safe_step_seen` | `observed`, and `known` for the current same-run reading with the expected value |
| `expose_contradicted` | `known_conflict`: equal-time readings that disagree give no token |
| `safe_step_covered` | `complete_sweep` |
| verdict `safe` | no `waiting` row: the step is `unblocked`. Only an admitted round makes it `ready` or `safe_alone`. |
| verdict `blocked` | a `waiting` row: the token is current with another value (`current(run, token, "known", value, …)`), or a refutation at the current cut, `loop_step_safety_check` with verdict `refuted` and reason `violated-invariant` |
| verdict `unknown` | a `waiting` row with no current value for the token, or a check with verdict `unknown` and reason `missing-coverage` |

### 2.3 What stays the platform's

What is domain stays: the step's binding (expose a listener, retire a provider, restore a copy), the service needs, the restore bindings, captures and readbacks, and `managed_backup_restored`. A listener exposed without its protection, and a running consumer whose provider goes, are intermediate invariants of the platform (`intermediate_invariants` of the compiled pack). The certifier checks them in the variant and reports a violation as a refuted step check with its offending bindings, which `std-loop` turns into `waiting`. A restore dependency reading is a `LoopObservation` of the restore run, and the matching readback confirms the restore step's completion token, so `done` follows from `std-loop`.

### 2.4 Order, and the tests that already exist

- `safe_step.dl` and `safe_step.yaml` go in the pull request that makes red test C green.
- `examples/platform/proof_cases/test_startup_transition_cases.py` held the expectations of `safe_step.dl`. This pull request restates them in the terms above, in place, so the test keeps its id, which [safe transition rounds](safe-step-rounds.md) section 7 and the reason of `test_platform_safe_rounds_recorded` name. It becomes red test C. The old assertions read a relation that this decision retires; a worker cannot change them, so they change here, and `safe_step.dl` is without a test of its own until it goes.
- `test_restore_offline_dependencies.py` and `test_restore_offline_missing_binding.py` stay green beside test C. Once C is green, a planner pull request retires `restore_offline_result` together with those cases, which C then holds.
- `test_platform_safe_rounds_recorded` writes `safe_*` records. A planner re-encodes them through section 2.2 before that test is attempted; its reason says so.
- `test_five_scenes.py::test_platform_imports_std_loop` already holds the import and that no platform rule redeclares a core loop relation. No test here repeats it.

## 3. The smaller items

| Item | Choice | Why |
| --- | --- | --- |
| `run/packs/offer-selection/questions.yaml` copies the `grounds` question of `std-explain`, because the pack does not import it | **Import `std-explain`** and drop the copy; the reader keeps `proof: grounds` (red test D) | `invoice-drift` already does this. |
| `run/packs/cleanup-deadline` keeps `deadline_us` and `watermark_us` | **Keep, for now; map onto `std-loop` later** (red test F) | The cleanup deadline is an approved absolute instant ([server deadline](run-server-deadline.md)). `std-loop`'s `LoopDeadline` counts a budget from a start observation of the same run, so mapping onto it today would compute a budget from two instants, a supplied value that a rule should derive. The mapping waits until `LoopDeadline` can name an absolute boundary, a decision of the loop track. Then the attempt is a `LoopStep`, `cleaned` its completion, the watermark the event time of the current complete `LoopSweep`, and `overdue` is `std-loop`'s `deadline_expired`. |
| `run/packs/dispatch` has its own approval, decision and expiry | **Keep, for now; map onto `std-decision` later** (red test G) | An approval authorizes one attempt bound to a plan hash, a currency and a cost cap, and expires at an instant in microseconds. `std-decision` has validity in days and no bound object or amount, so an approval as a `Decision` today would decide differently on the day it expires. The mapping waits until `std-decision` can bound a decision's validity at an instant, a decision of the language track. Then an approval is a kind of the pack that is a `Decision`: the approver is its `decider`, its expiry its validity, and the plan hash, currency, cap and outcome stay its own slots. |
| `std-review` is imported by no pack | **The platform imports it** (red test E) | Scene 2 has review as a required area, and the platform already imports `std-access` at the pin `std-review` uses. Reading the tenant connection reviews (`TenantReviewDecision`) as `std-review` reviews is a follow-up with its own decision, because it changes the tenant request contract. |

F and G stay red until their prerequisite has its own decision and implementation. Their present tests, `run/tests/test_cleanup_deadline.py` and `run/tests/test_dispatch_policy.py` with the offline replay case in `run/fixtures/offline/`, write the slots that go, so a planner restates them first, as in step 2 of section 1.4.

## 4. Red tests

Each test takes its expectation from this decision and from the contracts of the standard packs. Each fails today with an `AssertionError` before it builds any input.

- **A** `M3:` `compiler/tests/test_std_decision_dates.py::test_std_decision_rules_read_dates`: the rules of `std-decision` read `decision__valid_from`, `decision__valid_until` and `reference_date__date`, and no rule of `std-decision` or of a pack that imports it reads `decision__valid_from_day`, `decision__valid_until_day` or `reference_date__day`. A dated scenario gives "in force on" from the dates alone: a start on the reference day counts, an end on it does not, a successor replaces from its own start, and an inverted window is found.
- **B** `M3:` `examples/subsidy/test_subsidy_dates.py::test_subsidy_schema_has_no_day_numbers`: no slot of the subsidy schema ends in `_day`, the dates it kept are `date` slots that the rules read, and no view reads a number as `yyyymmdd`. It follows A.
- **C** `M2:` `examples/platform/proof_cases/test_startup_transition_cases.py::test_startup_transition_cases`: `safe_step.dl` and `safe_step.yaml` are gone, and the startup, retirement and restore cases give the `std-loop` rows of section 2.2.
- **D** `extra:` `run/tests/test_offer_selection_std_explain.py::test_offer_selection_imports_std_explain`.
- **E** `extra:` `examples/platform/test_platform_std_review.py::test_platform_imports_std_review`.
- **F** `extra:` `run/tests/test_cleanup_deadline_std_loop.py::test_cleanup_deadline_is_a_std_loop_deadline`: cleanup-deadline imports `std-loop` pinned to its hash, has no `deadline_us` or `watermark_us` slot, and its compiled pack derives `deadline_expired`.
- **G** `extra:` `run/tests/test_dispatch_std_decision.py::test_dispatch_approval_is_a_std_decision`: dispatch imports `std-decision` pinned to its hash, its approval kind is a `Decision`, it has no `expires_us` slot, and its compiled pack derives `in_force_on`.

## 5. Settled by the owner

The owner settled the open choices of the draft pull request on 20-11-2026 by following the advice:

1. **Dates.** Rules compare dates in their native order; `rezono 1` and the `.dl` rules read `Date` directly. `@days` is only for day arithmetic, such as a horizon in days (section 1.2).
2. **Slot name.** The reference date's date is `ReferenceDate.date`; `on` is a keyword.
3. **`cleanup-deadline` and `dispatch`** stay as they are for now, each with a red test for its later mapping (F and G, section 3).
4. **`std-review`.** The platform is its first consumer (E). Reading `TenantReviewDecision` as `std-review` reviews is a follow-up with its own decision.

## Alternatives

- **Keep the day numbers until Rezono 1 replaces the Datalog rules.** The stopgap would then live on in every pack written before that, and the numbers would be carried into the Rezono form by the candidate acceptance tests, which compare the two forms row by row.
- **`@days` for every comparison of dates.** It needs no construct beyond the `days` assignment, but a plain comparison would then go through a number that each witness carries beside the date, and the `.dl` form would read differently from `rezono 1`, which compares `Date` values directly. Native order keeps the two forms alike; `@days` stays where a number of days is the point.
- **Retire the slots in one pull request.** The rules, the schema, seven pins and the test rows of four tracks would land together, and a lifted mark may not stand beside the test changes. The steps of section 1.4 keep every pull request inside the policy.
- **Map the platform's `safe_*` kinds onto `std-loop` with a view and keep them.** That keeps the variant the vision rules out, and a view cannot supply what `std-loop` requires and the platform kinds lack: an event time, a state and a token.
- **Let the platform derive its own verdicts and also publish `std-loop` rows.** Two rule sets would answer the same question, and the reader would have to know which one binds.
