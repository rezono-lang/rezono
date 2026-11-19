# Derive task claim release from observed leases

A task claim is a Git ref. Releasing an abandoned claim deletes that ref, which is a nonrepeatable effect on shared state. Derive the release plan by rule from dated observations of the ref, its last push, the lease decision and the pull requests for its branch. Keep the delete and its readback outside the rules, in small adapters, and confirm the release only from a later complete read in the same run. This makes the claim release section of [build reconciliation](build-reconciliation.md#claim-release) executable. [Claim model](../formal/Claims.tla) · [Effect contract](../contracts/effect.yaml) · [Scoped completeness](scoped-completeness.md)

## 1. Observed kinds

Every row belongs to one verified `BuildRun` cut. Times are integer Unix seconds in UTC, recorded by the adapter that read them. A claim is evaluated in any verified build run, whatever event started that run.

| Kind | Independent origin and acceptance question |
| --- | --- |
| `BuildClaim` | The ref listing under `refs/heads/task/` at the cut. Which claim branch existed, at which generation? The generation is the full commit ID of the ref tip. |
| `BuildClaimActivity` | The server's activity records for the pushes to that ref, one row per push with the activity answer as its source and the exact whole-second push time. When did the push that produced this generation happen? The rules take the latest push, and it supplies a lease start only when its resulting commit equals the observed generation. Two equally recent pushes with different commits leave the latest push undecided, so the claim gets no lease start. |
| `BuildClaimLease` | A `std-decision` decision states the lease duration in seconds. Which duration is in force on the policy date of the cut? The first decision sets four hours. |
| `BuildClaimPullReading` | A query for pull requests whose head is the claim branch, at the cut. Is a pull request open for this claim, or did the complete answer contain none? A `none` reading names the `LoopSweepReceipt` of its run and cut that attests the complete read. An empty answer without that receipt, an unreadable answer and a mismatched answer produce no row. |
| `BuildClaimDelete` | The conditional delete adapter's record of one attempt. Which generation of which branch did it try to delete, when, and was the answer `sent`, `refused` or `unknown`? It names the branch, not a `BuildClaim` row, because the release and its readback concern the ref. |
| `BuildClaimRefRead` | A complete ref listing after the delete, bound to a `LoopSweepReceipt` of the same run and time. Was the branch `absent`, or `present` at which generation? |

The fields are those of the acceptance tests in section 4. Use string enumerations for states. Do not use booleans in rule inputs.

## 2. Release plan

`build_claim_release_plan(run, claim, generation, reason)` holds at a verified cut when all of the following hold:

- the claim is observed at the cut tick with that generation;
- its activity record names the same generation and gives the lease start;
- exactly one lease duration is in force on the run's policy date;
- the lease start plus that duration is at most the cut tick, as in the model's `now >= leaseUntil`;
- a pull reading for the claim at the cut tick says `none` and names a `LoopSweepReceipt` of the run at that tick, and no reading at that tick says `open`.

Otherwise the claim is held. `build_claim_held(run, claim, reason)` names each failing ground with one of `lease-active`, `lease-unknown` (the latest push record of the claim did not make this generation, two equally recent pushes made different commits, or there is none), `lease-policy-unknown`, `pull-request-open` (some reading at the cut tick says `open`) and `pull-request-unknown` (no reading at the cut tick, or only a `none` reading without such a receipt). A claim listed only at an earlier tick is not at the cut and gets neither row. A claim with a release plan has no held row. A renewed claim has a new generation and a new push, so an old activity record cannot release it. Missing or contradictory evidence never yields a plan.

A plan is not a release. Eligibility alone yields only the plan, as the build decision requires.

## 3. Delete and confirmation

The delete adapter rechecks the pull requests for the branch immediately before it acts. An open or unreadable answer skips the delete and records nothing. Otherwise it runs one conditional push, `git push --force-with-lease=refs/heads/<branch>:<generation> origin :refs/heads/<branch>`. The lease makes the delete fail if the ref moved. Exit status zero records `sent`. A rejection that reports a stale lease or a rejected ref records `refused`. Any other failure, including a timeout, records `unknown`, because the ref may or may not have been deleted. GitHub cannot serialize the pull-request check with the delete, so the recheck narrows the window that the model closes with `CheckOpenPR`. The ref lease still guards the generation.

`build_claim_released(run, branch, generation, reason)` requires a `sent` or `unknown` delete of that generation and a later `absent` ref read of the branch in the same run, bound to a receipt of that run and tick, with no `present` read at that tick. This is the model's `Confirm`. A later receipted read that shows the branch at another generation gives `build_claim_release_discarded(run, branch, "replaced")`, the model's `DiscardConfirmation`. A `refused` delete gives `build_claim_release_discarded(run, branch, "delete-refused")` and nothing else. Every other delete that is neither released nor discarded gives `build_claim_release_pending(run, branch, reason)`: `still-present` when a later receipted read shows the same generation, otherwise `readback-missing`. A read from another run, an earlier read and a read without its receipt confirm nothing.

## 4. Queue reading

The planner queue in [build reconciliation](build-reconciliation.md#task-and-queue-observations) counts the open pull requests against the default branch that are not drafts. Read it from a complete listing. The reading names the `LoopSweepReceipt` of its run and cut that attests the complete listing, and the rules count it only with that receipt. An incomplete listing, or a pull request whose number, state, draft flag or base is missing, produces no `BuildQueueReading`, so the existing rules report `queue-evidence-unknown`.

## 5. Acceptance

| Test | Independent expectation |
| --- | --- |
| `test_build_claim_release_plan` | Hand-worked lease arithmetic and the guards of `Delete` in the claim model. Only the claim whose lease ended at or before the cut, with a matching push record and a complete empty pull reading, gets a plan. Each other claim fails on exactly its own missing ground. |
| `test_build_claim_latest_push` | Hand-worked lease arithmetic over several push records per claim. Only the latest push starts a lease, and only when it made the observed generation. |
| `test_build_claim_release_confirmation` | The `Confirm` and `DiscardConfirmation` actions of the claim model. A same-run absent read after the delete confirms; a replacement, a refusal, an earlier read, a foreign run or a missing receipt do not. |
| `test_build_claim_capture` | Hand-written ref listing and activity answers in GitHub's documented JSON shape. Only task refs become claims; a stale activity record gives no lease start. |
| `test_build_claim_pull_capture` | Hand-written pull answers. An open pull request, an empty answer, an unreadable answer and an answer for another head each give their own reading or none. An empty answer without a receipt of the same run and cut gives none. |
| `test_build_claim_delete` | A recorded fake Git runner. The adapter issues exactly the conditional delete, skips it on an open or unreadable recheck, and records `sent`, `refused` and `unknown` as defined above. |
| `test_build_queue_capture` | A hand-written pull listing. Drafts, other base branches and closed pull requests do not count; an incomplete listing, a listing without a receipt of the same run and cut, and a pull request with a missing field give no reading. |

## Alternatives

- **Keep release in the cleanup script only.** The script works, but its policy cannot be compared with the rules or explained with a proof. The build decision asks for both during transition.
- **Treat a successful push as the release.** The model's `ConfirmationReadsAbsence` property requires a read of absence after the delete. A push can succeed against a ref that is then recreated.
- **Use the tip commit's committer time as the lease start.** Anyone who pushes can choose that time. The server's push record is independent of the claimant.
