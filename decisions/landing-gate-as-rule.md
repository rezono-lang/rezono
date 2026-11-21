---
decider: [owner, loop, core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: landing-gate
---

# A pull request lands only when the build pack concludes that it may land

On 2026-11-21 the steering of this repository went wrong outside Rezono, in three ways. Read labels `p1-read-<sha>` ([checker and access review](checker-and-access-review.md)) appeared within minutes of each push, without a reading. Pull requests went back into the merge queue without a new commit. Two drivers worked against each other on the same pull requests. Each time a script or an agent held a conclusion that nothing derived: a label stood for "this head was read", and enabling auto-merge stood for "this pull request may land". The owner decided (steering point 103) to make the landing gate a Rezono rule with a proof. This decision says what the rule concludes, which facts it reads, how the queue is entered and left, and what becomes of the label. [Build reconciliation](build-reconciliation.md) · [Review and rights](review-and-rights.md) · [Loop engine epoch](loop-engine-epoch.md) · [Tooling does not decide](tooling-does-not-decide.md) · [Facts and derivations](facts-and-derivations.md)

The rules live in the build pack (`build/`), which already decides check selection by rule ([tooling does not decide, Form 3](tooling-does-not-decide.md#23-change-to-target-selection-build-starting-with-scriptscomponentspy)). Readings and findings are review facts in `std-review`. Enqueue and dequeue are effects in `std-loop`. The build pack imports `std-review` for this, beside `std-access`, `std-decision` and `std-loop`.

## 1. The conclusion: may this head land

The build pack derives one landing state for every pull request head it observes at a verified cut ([section 2.1](#21-the-pull-head)):

`build_landing(run, change, head, state)`, with `state` one of:

| State | Means |
| --- | --- |
| `yes` | the pull request may land at this head; the row's proof is its witness |
| `no` | it may not land at this head; at least one ground says what to repair |
| `unknown` | nothing contradicts landing, but something it waits on is not there; the grounds name each thing |
| `invalid` | the evidence about this head contradicts itself; the grounds name each contradicting row |

There is exactly one row per `(run, change, head)`. The state is the four-valued `and` of three parts, by the truth table of [four-valued and/or parity](four-valued-and-or-parity.md#1-normative-truth-table-and-and-or): a part that is `no` makes the state `no`, whatever the others are; otherwise an `invalid` part makes it `invalid`; otherwise an `unknown` part makes it `unknown`; otherwise it is `yes`.

| Part | `yes` when | `no` when | `unknown` when | `invalid` when |
| --- | --- | --- | --- | --- |
| **Checks** (section 2.2) | every required check has one `green` reading of this head at the cut | a required check reads `red` | a required check has no reading, or reads `pending` or `skipped` | a required check has two readings at the cut that differ |
| **Reading** (sections 2.3 and 2.4) | no changed path needs a reading, or every active correctness reading of exactly this head is clean | every active correctness reading of this head records a correctness finding | a reading is needed and no active correctness reading of exactly this head exists | one active correctness reading of this head is clean and another records a correctness finding |
| **Quality** (section 2.4) | no quality finding of the change is open for this head | a quality finding of the change is open for this head | never | never |

Every part that is not `yes` also gives its grounds:

`build_landing_ground(run, change, head, state, ground, row)`, where `state` is the state of that part and `row` the identifier of the row that grounds it:

| `state` | `ground` | `row` |
| --- | --- | --- |
| `no` | `check-red` | the `BuildCheckReading` |
| `no` | `correctness-finding` | the `ReadingFinding` |
| `no` | `quality-finding` | the `ReadingFinding` |
| `unknown` | `check-missing` | the `BuildRequiredCheck` |
| `unknown` | `check-pending`, `check-skipped` | the `BuildCheckReading` |
| `unknown` | `reading-missing` | the `BuildPath` that needs the reading, or the reason of a full selection (section 2.3) |
| `invalid` | `check-conflict` | each `BuildCheckReading` of the conflict |
| `invalid` | `reading-conflict` | each `Reading` of the conflict |

So "no reading yet" is `unknown` with a `reading-missing` ground that names the path it waits on, a recorded correctness finding is `no` with the finding as its witness, and two readings of one head that disagree are `invalid`, as two valid opposite reviews are a conflict in [review and rights](review-and-rights.md#8-four-checks-that-block). A `yes` row has no ground rows: its proof, published with the other build relations, is the witness of the head, the readings and the green checks it rests on.

The reading part is also published on its own, `build_landing_read(run, change, head, state)`, because the policy check reads it (section 5).

## 2. The inputs

All inputs are observed at the verified cut of the run (`build_verified_cut`), as the other build observations are ([build reconciliation](build-reconciliation.md)). An observation without a source, or whose receipt is not of this run at this tick, counts for nothing.

### 2.1 The pull head

`BuildPullHead {id, run: BuildRun, change: Change, head_sha: Commit, observed_at: integer, source}`: the host listed this pull request with this head at the cut. The landing state is derived only for a pull head whose `head_sha` is the run's own `head_sha` and whose `observed_at` is the run's tick, so the changed paths, the check readings and the readings all concern the same commit.

`change` is a `Change` of `std-review`. The capture writes one per pull request: `id` is `pr-<number>`, `author` the pull request's author as the host names it, `content_sha256` the SHA-256 of the canonical JSON `["git-commit", <head sha>]` and `support_sha256` that of `["git-commit", <base sha>]`. A push therefore changes the content hash, and the review states of `std-review` see the change as new, as [review and rights, section 6](review-and-rights.md#6-a-changed-content-or-support-makes-an-acceptance-stale) wants.

### 2.2 Required checks

`BuildRequiredCheck {id, check}` are facts of the build pack in `build/facts/landing.yaml`, one per check that must be green before a pull request lands. Their origin is this decision, cited in the sidecar as a `git` source that names `decisions/landing-gate-as-rule.md` ([fact origins](fact-origin-required.md)). The checks are those the host's ruleset for `main` requires on 2026-11-21:

| Check |
| --- |
| `check` |
| `Inspect test evidence` |
| `Light checks` |

The host's ruleset is a projection of these facts. A change to the set is a change to this file, decided like any other.

`BuildCheckReading {id, run: BuildRun, head_sha: Commit, check, state: BuildCheckState, observed_at: integer, source, receipt: LoopSweepReceipt}` is one check of the head as a complete read of the host's check runs gave it at the cut. The capture maps the host's conclusion to the state; this mapping is the only thing it decides, and it is a reading of the host's vocabulary:

| `BuildCheckState` | Host conclusion or status |
| --- | --- |
| `green` | `success` |
| `red` | `failure`, `cancelled`, `timed_out`, `action_required`, `startup_failure` |
| `pending` | `queued`, `in_progress`, `waiting`, `requested`, `pending` |
| `skipped` | `skipped`, `neutral`, `stale` |

A skipped required check is not green: a check that did not run proves nothing ([AGENTS.md](../AGENTS.md), rule 4).

### 2.3 Which heads need a reading

The paths of [checker and access review](checker-and-access-review.md#the-paths-read-first) become facts of the build pack, in the shared form of change-to-target selection: one `BuildTargetRule` per path with `target: correctness-reading` and `kind: direct` (a folder as `path_prefix` with its `upper_bound`, a file as `path_prefix` alone), and one rule with `kind: full_fallback`. Their origin is a `git` source that names `decisions/checker-and-access-review.md`. The tables `READ_FIRST_DIRS` and `READ_FIRST_FILES` in `scripts/red_guard.py` then repeat these facts until section 5 retires them.

`build_reading_needed(run, change, head, row)` holds:

- for each recorded changed path (`BuildPath`) of a covered run that a `correctness-reading` rule selects, unless the run's admitted receipt lists the same path as a test file (`["test-file", path]`, the suite inventory the build pack already reads); `row` is the `BuildPath`;
- for each reason of a full selection of the run (`build_full_selection`): when the build scope is not known, a reading is needed (fail closed); `row` is that reason.

The test exemption is narrower than the sentence in [checker and access review](checker-and-access-review.md#the-paths-read-first), which also exempts fixtures and `conftest.py`: only a file that the admitted inventory lists as a test file is exempt. A fixture under a read-first path is read. This keeps the classification out of code; a later decision may add fixture folders as facts.

### 2.4 Readings and findings are review facts in `std-review`

`std-review` gets four kinds, bound to the full head commit, and the rules that read them. Like the rest of the pack, it assesses readings that were admitted; it authenticates nobody.

| Kind | Slots | Means |
| --- | --- | --- |
| `Reading` | `id`, `change: Change`, `commit_sha` (40 lower-case hex), `scope: ReadingScope` (`correctness` or `quality`), `reader`, `source` | someone read the difference of exactly this commit, for correctness (the paths of section 2.3) or for quality ([no green by the cheapest route, section 3](no-green-by-cheapest-route.md#3-pre-queue-reading-review)) |
| `ReadingFinding` | `id`, `reading: Reading`, `concern: FindingConcern` (`correctness` or `quality`), `source` | the reading found something |
| `ReadingDismissal` | `id`, `reading: Reading`, `source` | the reading is withdrawn; it counts for nothing, and its row stays |
| `FindingResolution` | `id`, `finding: ReadingFinding`, `commit_sha`, `source` | the finding was checked again at this commit and is resolved there |

No slot holds a day number: a reading is about a commit, not a day.

- `reading_active(reading)`: it has a source and no dismissal.
- A correctness reading of a commit is **clean** when it records no finding of concern `correctness`, and **found** when it records at least one. A clean reading and a found reading of the same commit and change are a conflict (`head_read_conflict`).
- A finding of concern `correctness` belongs to the commit its reading read. A new push is a new commit and needs its own reading; the old finding does not carry over, as a correctness finding today is repaired and the new commit read again.
- A finding of concern `quality` belongs to the change, whatever commit its reading read. It stays open for every head of the change except one that a `FindingResolution` of it names. A push therefore does not close a quality finding; only a resolution at that very head does.
- A reading counts only for its own change, only with `scope: correctness` for the reading part, and only for exactly its `commit_sha`. A reading of another commit, of another change or for quality only is not a reading of this head.

Until a review intake exists ([review and rights, the boundary of the gate](review-and-rights.md#where-the-acceptance-cases-go)), a thin reader records readings from the host: a review on the pull request whose `commit_id` is the head becomes a `Reading`, and each finding it states becomes a `ReadingFinding`. A label is never a reading.

## 3. Enqueue and dequeue are `std-loop` effects with a claim

A driver is a `std-loop` run that acts on the merge queue. Its acts are effects of the steps `enqueue` and `dequeue`, planned, attempted once per plan and read back by the rules of `std-loop` ([loop engine epoch, section 5](loop-engine-epoch.md)).

- **The plan.** `BuildQueuePlan {id, plan: LoopEffectPlan, change: Change, head_sha: Commit, action: BuildQueueAction, gate_run: BuildRun}` binds an effect plan of the driver's run to one pull request, one head and one action (`enqueue` or `dequeue`), and names the build run whose landing state it acts on. The plan's identifier, its idempotency key, is the SHA-256 of the canonical JSON `[action, change, head]`. So one head is enqueued at most once: once an attempt of that plan is journaled, `std-loop` plans it no more, and a pull request does not go back into the queue without a new commit. A second enqueue of the same head needs a `std-decision` `Decision` that names it; its identifier joins the key.
- **The claim.** One driver acts per pull request. Before it plans, a driver claims the pull request with a write-once ref `refs/rezono/queue-claims/<change>`, created with an empty lease as the [shared claim](run-shared-claim.md) does, holding its run. The capture lists these refs at the cut as `LoopClaim` rows: `run` the holder, `subject` the change's identifier (`pr-<number>`, which no other claim uses as its subject), `observed_at` the cut tick. `build_queue_driver(run, change, driver)` holds when exactly one such claim with a source is observed at the run's cut; two claims for one pull request leave it without a driver (fail closed).
- **Permission.** The build pack extends `effect_permitted` of `std-loop`:
  - `enqueue` for the plan's run when it is the pull request's driver at the gate run's cut and `build_landing(gate_run, change, head, "yes")` holds;
  - `dequeue` for the plan's run when it is the driver and the gate run's landing state for the head is anything but `yes`.

  A run that does not hold the claim gets no permission, so `std-loop` plans no effect for it.
- **The act.** The effect adapter enqueues through the host's call bound to the expected head (GitHub's `enqueuePullRequest` with `expectedHeadOid`), so the host refuses it when the head has moved. It dequeues with `dequeuePullRequest`. Drivers do not enable auto-merge: auto-merge enqueues later without the gate.
- **The read-back.** After an attempt, the driver reads the merge queue at a later sweep: a `LoopEffectReadback` of the plan is `expected` when the queue holds the pull request at that head (enqueue) or does not hold it (dequeue), `before` when it still shows the old state, and `other` otherwise. `std-loop` settles the effect from it.
- **Release.** The claim ref is deleted when the pull request has landed or closed, by the release effect of [build claim release](build-claim-release.md). A driver that stops leaves its claim; another driver takes over only after that release.

## 4. The label is a projection of the conclusion

The label `p1-read-<sha>` stops being an input. It may be set only on a pull request whose head is `<sha>` and only while `build_landing(run, change, <sha>, "yes")` holds at the latest verified cut. It is set and removed by the pull request's driver, as an effect of a step `label` with the same claim and read-back. A person or script that sets it by hand sets nothing that any check reads. A label observed on a head whose landing state is not `yes` is drift: the projector removes it.

## 5. How `scripts/red_guard.py` moves to reading the conclusion

Today `red_guard.py` keeps a pull request red until it carries `p1-read-<head>` when a read-first path changes. After the move, a later worker task:

1. The policy job (`Inspect test evidence` in `.github/workflows/red-policy.yml`) reads the checked build publication of the pull request's head, through a thin reader like `loop/build_selection_outcome.py`, and takes `build_landing_read(run, change, head, state)` for that head. It passes the read-first rule only when the state is `yes`. `no`, `unknown`, `invalid`, a missing row, a missing or unverified publication, or a publication of another head keep the job red, and its message names the grounds.
2. It reads the reading part, not `build_landing`. The policy job is itself one of the required checks (section 2.2), so reading the full conclusion would wait on itself. The reading part rests on no check.
3. `READ_FIRST_DIRS`, `READ_FIRST_FILES`, `read_first()` and the label branch of `review()` leave the production path. `read_first()` may stay under `scripts/` tests as an independent oracle (fate (b)) that compares its classification with the `correctness-reading` facts; it is no fallback. `--labels` is no longer passed.
4. In the merge queue nothing changes: the guard reads no labels there today, and the queue is entered only through a permitted `enqueue`.

## 6. Red tests

The tests are strict (`strict=True`, `raises=AssertionError`) and marked `M2`: the gate belongs to the build loop of release 1 ([release 1 scope](release-1-scope.md)). Each builds its rows by hand from this decision and evaluates the build pack on the batch backend. The read-first paths and the required checks come from the pack's own facts, so the tests also hold those facts to this decision and to [checker and access review](checker-and-access-review.md).

| Test | Expects |
| --- | --- |
| `loop/tests/test_landing_gate.py::test_unread_head_on_a_checker_path_is_unknown` | a head that changes `checker/rezono_checker/` with all required checks green and no reading is `unknown`, with exactly one ground `reading-missing` naming that path; an admitted test file under `k8s-admission/` needs no reading; the control, a head that changes only `docs/`, is `yes` |
| `loop/tests/test_landing_gate.py::test_a_finding_for_the_head_blocks_landing` | a correctness finding on the head is `no` with the finding as ground and as a premise of the proof; a clean and a found reading of the same head are `invalid` with both readings as grounds; dismissing the found reading gives `yes`; an open quality finding found at an older head is `no` until a resolution names this head |
| `loop/tests/test_landing_gate.py::test_a_reading_of_another_sha_does_not_count` | a clean reading of the previous head, of this head but another change, or of this head for quality only leaves `unknown` with `reading-missing`; a clean correctness reading of exactly this head gives `yes`; the required checks are the three of section 2.2 |
| `loop/tests/test_landing_gate.py::test_a_second_driver_without_the_claim_gets_no_enqueue` | with a `yes` landing state, only the driver whose claim is observed at the cut gets `effect_planned` for its enqueue plan; no claim, two claims, a claim observed at another tick, or an `unknown` landing state plan nothing for either driver |

## 7. Follow-up worker tasks

1. `std-review`: the kinds and rules of section 2.4 (`rules/reading.dl`, the kinds beside the others in `schema/review.yaml`), its new hash in `compiler/rezono_compiler/standard_packs.py`, and the re-pin of its importers.
2. `build/`: import `std-review`; the kinds of sections 2.1, 2.2 and 3; `build/facts/landing.yaml` with the required checks and the `correctness-reading` target rules and their sidecar; `build/rules/landing.dl` with `build_landing`, `build_landing_ground`, `build_landing_read`, `build_reading_needed`, `build_queue_driver` and the `effect_permitted` clauses; labels. These turn the four red tests green.
3. Captures, thin readers of fate (d): pull heads and `Change` rows, check readings with their receipt, readings and findings from host reviews, and queue claim refs.
4. The queue effect adapter (`enqueuePullRequest` with `expectedHeadOid`, `dequeuePullRequest`) and its read-back of the merge queue.
5. The label projector of section 4.
6. `scripts/red_guard.py` and `.github/workflows/red-policy.yml` move to the conclusion as section 5 says. `red_guard.py` is a policy path; the change is read after it lands, like every workflow change.

## Alternatives

- **Keep the label and tighten who sets it.** The label held a conclusion that nothing derived. Tightening the hand that sets it leaves a conclusion stored as a fact ([facts and derivations](facts-and-derivations.md)), and the failures of 2026-11-21 came from exactly that.
- **Gate in `red_guard.py` alone.** It would keep the decision in Python, against [tooling does not decide](tooling-does-not-decide.md), and give no proof that a reviewer, a driver and the policy job can all read.
- **Make the gate a GitHub ruleset with required approvals.** The repository's pull requests are opened under the owner's account, and the host does not let the author approve; a ruleset also has no notion of the read-first paths or of a reading bound to one commit.
- **Let a finding at an older head close with the next push.** That is green by the cheapest route: push, and the finding is gone. A quality finding stays open until a resolution names the head.
- **Last driver wins.** Two drivers racing on the queue is what happened. A write-once claim makes one of them act, and `std-loop` already settles an effect once per plan.
- **Treat a conflict of readings as `no`.** It hides a disagreement between readers as an ordinary finding. `invalid` says that the evidence itself must be settled, by a dismissal or a new reading, as [review and rights](review-and-rights.md) does for opposite reviews.
