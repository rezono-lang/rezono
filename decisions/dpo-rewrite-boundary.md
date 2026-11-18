# Keep double-pushout rewriting at the design stage

Represent a proposal or a question's assumption as a difference in typed rows
over a pinned state. A replacement removes the old row and inserts the new one.
An assumption changes only the question's evaluation state. Keep the rows and
evidence that define the pinned base available for replay.
[Rezono assumptions](../docs/rezono/expressions.md)

## A rewrite and its match

A double-pushout (DPO) rewrite is a span `L ← K → R`. The left side `L`
describes the rows to find, `K` the rows to preserve, and the right side `R`
the rows to have afterwards. For a match `m` in the current state and a
right-side realization `m′` that agrees with `m` on `K`, the delta is
`−m(L ∖ K) + m′(R ∖ K)`. Preserve the identities in `K` and give added rows
fresh identities when the rewrite introduces them. Deletion must leave the
remaining references well formed.

Express matches as rules over typed relations. Their positive premises bind
the rows to the match. A negative application condition is a `not` premise
using the same bindings. Evaluate it against the state at the point of
application, with the completeness required for absence to count as evidence.

## What the existing mechanisms cover

- A rewrite could establish applicability for a type of change before it
  runs. Today, ordinary integrity checks inspect the resulting candidate
  state and block an invalid result.
  [Compiler integrity checks](../compiler/rezono_compiler/emit.py)
- A rewrite could give a cheap test of whether two proposals touch each
  other's matches, deletions, or negative guards. Today, the proposal
  publisher applies the supplied delta to the pinned base and checks the
  resulting candidate. A candidate with both edits goes through those same
  checks. This catches capacity clashes when the pack declares a capacity
  invariant. The capacity design gives an example of two individually
  admissible proposals that compete for the same remaining capacity.
  [Proposal publisher](../edge/publisher/rezono_publisher/proposal.py)
  [Combined-capacity design](platform-tenant-proposal-relations.md#capacity-on-the-combined-proposal)
- A rewrite could capture a reusable guarded change such as moving a service.
  Today, the reconciliation loop derives eligible steps from declared desired
  state and current evidence.
  [Reconciliation](loop-design.md)
- A rewrite plan could establish that every intermediate state in a sequence
  is valid. Today, `std-order` determines precedence. Its order checks leave
  the validity of intermediate states unproved.
  [Ordering rules](../packs/std-order/rules/order.dl)

## Candidate acceptance question

Given two proposals on the same pinned base, can each be applied after the
other, and do both orders yield the same final set of typed rows? Check the
match and each `not` premise again for the second proposal against the
intermediate state in its order. Require validity at every step. The comparison
should identify an inapplicable step or the rows that differ in the final
states.

Build a dedicated rewrite engine only when an acceptance question requires it.
Use AlgebraicRewriting as an independent oracle for matches and resulting row
deltas when that task is justified.
[Acceptance rule](../AGENTS.md#what-must-stay-true)

A planner that searches for a sequence of steps follows the solver proposal
boundary. Rules still check a proposed sequence against its requirements and
retain the evidence for each check.
[Solver proposals](solver-proposals.md)
