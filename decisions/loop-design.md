# Run-scoped reconciliation

## Existing behavior

At revision 8ef08bf, std-order computes transitive precedence and detects cycles and inconsistent ranks. The platform example supplies desired facts, rules and an independent oracle. The Python port runtime validates declarations, rejects unsuitable manifest epochs and constructs invocation records. The effect, observation, plugin and output-index contracts have validation fixtures. An invocation record does not execute a tool. The effect schema describes attempt states, and the output-index fixture associates knowledge witnesses with rendered fields. Neither establishes a running journal or a cluster reader. This decision specifies the missing reconciliation behavior.

## Relations and evidence

Use std-loop over std-order. Evaluate a finite declared set of steps for a pinned manifest, with immutable run ID and desired inputs. A token identifies an expected typed fact by row reference and desired value. Precedence adds the predecessor's completion token as a prerequisite. Each relation carries the run ID and a reason referencing its source rows. Preserve distinct witnesses while scheduling each step at most once per round.

| Relation and arguments after run ID | Derivation |
| --- | --- |
| needed(step, token, reason) | Declared requirement or precedence witness for the step. |
| known(token, reason) | Current evidence for the token in this run has known state and equals the expected typed value. |
| waiting(step, token, reason) | Unfinished step requires this token and no known row supplies it. Cite the requirement. |
| ready(step, reason) | Unfinished, eligible step has zero missing requirements. Cite its declaration and satisfied requirements, including the empty set. |
| done(step, reason) | Current matching evidence confirms the step's declared completion token. Cite the observation. |
| stuck(step, reason) | Evidence shows an order cycle, terminal refusal or expired observation deadline, or a complete observation sweep establishes an unresolved fixed point with no eligible producer or pending external operation. Cite the blocking rows. |

Use stratified rules, negation, counts and comparisons over finite inputs. A stuck step is ineligible. Compute structural blockers before readiness and diagnose a fixed point from the resulting frontier. Read observations through an envelope containing run ID, sweep ID and the existing Observation. Select the latest event time for each expectation in the active run. At equal times distinct incompatible values constitute conflicting evidence and cannot supply a token. Unknown and missing values cannot supply a token. Measure deadlines from a recorded start observation to a recorded sweep watermark, both in event time. Replay never consults a wall clock.

## Executor

Accept a checked manifest, run ID, positive round bound, initial evidence and declared ports. Each round computes a stable ready set, emits only its plans in step-key order, applies eligible plans, performs a complete observation sweep, then recomputes against the new evidence. Stop successfully when every declared step is done and the comparison yields no findings. Empty input succeeds immediately. A stuck step or a terminal drift finding gives a diagnostic failure. If another round is necessary after the bound, fail with the pending steps and witnesses. The executor contains no platform step names or numbered procedures.

Use declared plan, apply and status operations. Repeatable reconciliation proceeds within the approved run. A nonrepeatable effect requires approval binding its exact plan hash and a durable single-attempt claim before dispatch. An uncertain attempt is resolved through status using the same key, including after restart. Keep tool-specific ordering inside that tool.

## Observation and verification

Recover observed columns through the same invertible field binding used to render each knowledge-origin JSON pointer. The output index identifies the artifact and row witness. A witness alone may identify several columns, so retain the emitting column binding with the render metadata. Check object identity and manifest digest, use the declared type in both directions, and reject ambiguous or lossy mappings. Constants and defaults provide provenance only. Derive drift by rule from expected rows and current observations, referencing both the expectation and observation. A missing object requires an explicit absence observation from a completed sweep.

Use a small independent Python oracle for the six relations. For offline replay, hand-author two steps A and B with B requiring completion of A. From no observations the first round plans A, its sweep confirms A, the second plans B, and its sweep confirms B. The result is success after two rounds. A different run's A observation cannot shorten the trace.

The separate CI workflow creates one disposable runner-local cluster, uses a lightweight storage substitute, and selects the repository-wide pytest marker `cluster` for the loop, admission, translator and status reader together. The ordinary check excludes that marker. Verify a render/read round trip, convergence from empty state and evidence for the platform's prohibited recovery-zone flow and services without signed components. Always clean up the cluster.

## Alternatives

A scripted sequence would bake platform dependencies into the executor. A second reverse mapping would let the reader silently diverge from the renderer. An ambient clock would change deadline outcomes during replay. The selected design keeps ordering in facts, field identity in one binding and time in the evidence.
