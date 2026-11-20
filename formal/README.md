# Formal models for Rezono

[TLC model checks](../.github/workflows/formal.yml) run on pull requests that
change this directory or the workflow. The job checks the exact PR head and
verifies the SHA-256 of the pinned TLC release. Each model has a passing case
and a mutation that must fail on a named invariant. A clean run, a deadlock
or a different violation fails the mutation check.

| Model | Configurations that pass | Configurations that must fail |
| --- | --- | --- |
| [Epochs](Epochs.tla) | [Completion before marker](Epochs.cfg), [transaction with step-end relay](EpochsTxn.cfg) | [Push marker without waiting](EpochsNoWait.cfg) and [relay at the marker row](EpochsTxnAtRow.cfg) violate `Complete`. |
| [Effect](Effect.tla) | [Retained plan claim](Effect.cfg) | [Omit the retained claim guard](EffectNoLock.cfg) violates `AtMostOneSubmit`. |
| [Claims](Claims.tla) | [Lease, generation and open-PR checks](Claims.cfg) | [Omit the open-PR check at deletion](ClaimsNoOpenPRCheck.cfg) violates `SafeRemoval`. |
| [Rounds](Rounds.tla) | [Certified visible prefixes and observed completion](Rounds.cfg) | [Trust a submit](RoundsTrustSubmit.cfg) violates `DoneHasCurrentMatchingObservation`. [Check only the combined result](RoundsCombinedOnly.cfg) violates `EveryVisiblePrefixValid`. |

## Protocols and assumptions

**Epochs.** Three parts in a dependency graph process two epochs. A Feldera
step reads independently queued changes and markers. Its output rows can
arrive in any order before the step-end signal. A transaction consumes its
buffered changes and markers in one step. Downstream parts must receive each
change once, in its own epoch, before the manifest is published. A marker
written outside a transaction can overtake changes. A marker row in a
transaction can still arrive before its changes, so the relay waits for the
end of that step.

**Effect.** Two workers can submit a nonrepeatable effect for one plan hash.
The model assumes a durable conditional claim and a provider that can
create a second resource if called twice. A crash or uncertain reply can
leave an unknown outcome. Matching status evidence can reconcile it, and
confirmed cleanup leaves the used claim in place. The guarantee is about
the number of submissions and creations. A crash after claiming may leave
the effect unsubmitted.

**Claims.** A cleanup run reads one candidate ref after its lease expires.
Renewing or reacquiring the ref advances its generation. Opening a PR and
deleting a claim are atomic transitions on the same claim. Deletion compares
the observed generation and rechecks expiry and the open PR at the time it
takes effect. The cleanup run reports success only after it reads back
absence for that generation. A ref recreated before this read invalidates
the pending confirmation. The mutation permits a PR to open between the
read and the delete, so the deletion receipt records the unsafe removal.
The model bounds clock ticks and generations to check safety with a finite
state space.

**Rounds.** Two workers can claim and submit individual members of a batch
over two observation cuts and two run identities. An exposed resource needs
protection. An independent audit member allows two safe submissions and a
crash between them. The genesis cut starts from a certified empty base.
Later cuts need closed coverage of the observed state before evaluating a
batch. Deliveries may arrive in any order. Only a reading at the active run
and cut supplies current evidence. The model retains claims and submission history
across cuts and run changes. A later cut clears completion tokens and
reestablishes them through matching readback.

The model explores every allowed choice within its batch bound. It assumes
an effect becomes visible at one modeled boundary and an environmental
correction preserves safety before the new cut is observed. A missing
receipt or unreachable producer can leave the system waiting. Eventual
completion would require fairness and a responsive environment. See
[safe transition rounds](../decisions/safe-step-rounds.md).

## What ties a model to the code

A model proves properties of its protocol. The table lists tests that replay
the same actions against code in [loop](../loop/). **None** means that the
action has no direct replay there.

| Model | Action | Replay in the loop |
| --- | --- | --- |
| Epochs | `StepOver`, `Step`, `Commit` | None. |
| Epochs | `HandOn`, `Relay` | None. |
| Epochs | `Skip`, `Begin`, `Push`, `Mark`, `Done` | None. |
| Epochs | `Publish`, `NextEpoch`, `Finished` | None. |
| Effect | `Claim` | None for the durable conditional write. |
| Effect | `CrashBeforeSubmit`, `Submit` | None. |
| Effect | `ObserveUncertain` | None for recording the outcome. |
| Effect | `ReconcilePresent`, `ConfirmCleanup` | None. |
| Claims | `Tick`, `Acquire`, `Renew` | None. |
| Claims | `OpenPR`, `ClosePR`, `Observe` | None. |
| Claims | `Delete`, `Confirm`, `DiscardConfirmation` | None. |
| Rounds | `Evaluate` | None for certification of a batch. |
| Rounds | `Claim` | [Durable attempt claim](../loop/tests/test_round_claim.py) replays exclusive conditional claim creation, same-pin holder coalescing and persistence across cuts and runs. |
| Rounds | `SubmitOne`, `Crash`, `LoseReply` | [Round submit guard](../loop/tests/test_round_submit.py) replays the certified claim, crash, lost-reply and unknown-state guards without marking completion. None for physical dispatch. |
| Rounds | `Correct` | None for changing the physical resource. |
| Rounds | `Observe`, `Reconcile` | [Recorded correction](../loop/tests/test_recorded_correction.py) replays a late observation, rejects a foreign run and revokes completion on newer contrary evidence. |
| Rounds | `CloseSweep` | [Fixed-point replay](../loop/tests/test_replay_fixed_point.py) exercises complete and partial coverage. |
| Rounds | `NextRound` | [Recorded correction](../loop/tests/test_recorded_correction.py) replays the next observed frontier. None for replacing the pinned certificate. |
| Rounds | `ConcludeFixedPoint` | [Fixed-point replay](../loop/tests/test_replay_fixed_point.py) distinguishes terminal blocked evidence from pending completion. |

The [effect eligibility test](../loop/tests/test_attempt_approval.py) compares
the candidate with the approved plan hash.
[The uncertain attempt test](../loop/tests/test_uncertain_attempt.py) selects a
status read after an uncertain outcome. These tests cover prerequisites and
follow-up decisions around the formal actions.

From this directory, use the verified jar path as `TLA_JAR`.

~~~bash
java -cp "$TLA_JAR" tlc2.TLC -config Claims.cfg Claims.tla
bash must-fail.sh ClaimsNoOpenPRCheck.cfg Claims.tla
java -cp "$TLA_JAR" tlc2.TLC -config Rounds.cfg Rounds.tla
bash must-fail.sh RoundsTrustSubmit.cfg Rounds.tla
bash must-fail.sh RoundsCombinedOnly.cfg Rounds.tla
~~~
