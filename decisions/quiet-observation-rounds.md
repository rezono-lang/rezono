# Quiet observation rounds

Preserve the sweep identifier, run, recorded event time and completeness even
when a port returns no new values. In the typed recording format from
[the loop design](loop-design.md), such a sweep has `id`, `run`,
`event_time`, `complete` and an `observations` array. Its integer time uses
the same epoch and units as the recording's admitted records. The empty array
leaves object values alone. Each consumed sweep counts as a round.

In a replay the typed adapter emits a LoopSweepReceipt for the current
explicitly complete round. Older observation lists remain readable and can
advance the plan. They carry no independent closure receipt. A recording
that ends while its steps are still waiting reports `pending` and exits
with status 1. Reaching the configured round bound still reports failure.
A proved fixed point includes the run, sweep, blocked step, missing token
and prerequisite reference in the command's `fixed_point` array.

LoopSweep records carry this evidence. LoopDeadline attaches a step's budget
in event-time units to a start observation of the same run. At the inclusive
boundary an unfinished step is stuck and cannot be ready. LoopRequirement
names a token required by a step. LoopPendingOperation records an external
operation that can still supply a token. A current complete sweep can
establish an unresolved fixed point only when no step can advance and no
external operation can supply its missing token. An incomplete or foreign
sweep cannot establish it. The proof cites the relevant sweep and
declarations, and the start observation when the deadline expires.

Derive `round_outcome(run, state)` with states `pending`, `failure` and
`success`. A fixture can cause a deliberate discrepancy. Before execution,
a LoopExpectedDifference declares its run, token and observed value in the
pinned inputs. This exact comparison still produces its ordinary drift row
and proof. A different observed value or an undeclared difference blocks
completion. The executor consumes these derived decisions.

In the example, publication awaits an external permit. Its recorded start is
10 and the budget is five units. A quiet sweep at 14 leaves the step waiting
while an external operation is pending. A quiet sweep at 15 expires the
deadline. Without a pending operation, a complete sweep at 14 establishes a
fixed point unless a producer can advance. A different run has a later sweep
in all cases. Once publication completes, a deliberately denied probe stays
visible. Removing the declaration changes the terminal outcome.
