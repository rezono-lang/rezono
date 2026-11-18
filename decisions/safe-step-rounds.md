# Prove safe transition rounds

Use typed row deltas, the existing rule evaluator and independent certificates to select each executable round. Every visible outcome of a dispatched batch must preserve integrity and the pack's declared intermediate safety invariants. Rebuild the next round from observed state. This extends the reconciliation and observation contracts with a transition check. [Run-scoped reconciliation](loop-design.md) · [Quiet observation rounds](quiet-observation-rounds.md)

## 1. Pack interface and round identity

Pin the desired publication, run identity, observation cut and compiled rule definition. The cut identifies the admissible observation inputs and evidence receipts for this round, including the scope and event window of each completed read. Derive the modeled operational state `X` from those inputs. Keep desired rows, observations with their origins, and operational rows derived from the observations distinct. Vary only the modeled operational rows in a speculative evaluation. For example, a desired router rule, its readback and the resulting effective allowance are three distinct claims. [Observation contract](../contracts/observation.yaml)

| Pack declaration | Meaning |
| --- | --- |
| Match and identity | A rule binds a desired change to a finite domain of typed identities. The step key is the rule identity and its identifying bindings. Derive any fresh element keys from those bindings. Preserve distinct witnesses while scheduling each step key once. |
| Conditions | Positive premises, confirmable prerequisite tokens and forbidden patterns. Every forbidden pattern declares the scope that can establish its absence. |
| Effect | The exact signed row delta for the match, the old keyed rows it expects and the observable boundary of the effect. The external plan binds its exact input, target and promised delta. |
| Confirmation | The expected subject, attribute, typed value and token, together with the observation that can establish them. An indivisible effect with several changes requires a readback that covers its entire promise. |
| Intermediate safety | A finite, applicable inventory of named invariants, with the scope and grounds required to decide each. A violation names offending bindings. An undecidable invariant names its missing grounds. |
| Goals and selection | A finite inventory of required outcomes and their confirmations, a fixed positive batch width for each acceptance fixture, and an integer priority ordering for eligible policy-equivalent steps. The goal inventory also covers an outcome for which no step matches. |

Use LinkML schemas, sourced fact records and ordinary Datalog rules for the initial bindings. A pack binding maps typed effect rows to insert, delete, set and unset operations and names its invariant and coverage relations. Compile the binding once per pack. A replacement retracts the old value and adds the new value. An insertion supplies the keyed record and its required slots. A deletion or replacement identifies the existing rows it changes. The fact-delta contract supplies these operation meanings. The round certificate additionally binds the old rows and cut, since several rounds can share a desired manifest. [Delta contract](../contracts/delta.yaml) · [Speculative expression semantics](../docs/rezono/expressions.md)

One step is one independently observable effect. Split a multi-object apply wherever separate progress could become visible. Treat several row changes as indivisible only when the adapter has a documented guarantee and a test that verifies the promised boundary under failure. Plan the full readback of that boundary. The public effect plan hash and attempt key bind the operation independently of a round number, so reevaluating an unresolved effect cannot create another attempt. [Effect contract](../contracts/effect.yaml)

Use the six existing `std-loop` signatures and its import of `std-order`. Pin the loop import when wiring the platform pack to this interface. [Loop pack](../packs/std-loop/pack.yaml) · [Order rules](../packs/std-order/rules/order.dl) · [Platform imports](../examples/platform/pack.yaml)

| Relation | Round behavior |
| --- | --- |
| `needed(run, step, token, reason)` | Explicit requirements, completion of transitive predecessors, required readings and scope receipts. |
| `known(run, token, reason)` | Current same-run observation of the exact subject, attribute and expected value. Select by event time. Foreign, stale, unknown and equal-time contradictory evidence supplies no token. |
| `waiting(run, step, token, reason)` | False or missing grounds, forbidden matches, predicted violations, unresolved attempts or deferral by selection. Use a stable obligation key and a typed reason. A losing alternative cites the winner. |
| `ready(run, step, reason)` | Only members of the chosen certified batch, with the individual and batch proofs. An internal relation can expose steps safe on their own. |
| `done(run, step, reason)` | A current matching readback. A later contrary reading can revoke completion. |
| `stuck(run, step, reason)` | Existing terminal refusals and cycles, plus a witnessed fixed point that accounts for every unfinished goal, including a goal without a matching producer. |

Derive blockers before selection. Derive selection deferrals afterward so they cannot feed back into eligibility through negation. Keep the executable frontier a consumer of the certified selection. [Loop rules](../packs/std-loop/rules) · [Frontier](../loop/frontier.py)

## 2. Certify every visible state

Start only from a certified base. Check keyed integrity, required relations and attributes, functionality, references and path equalities, as applicable, together with every designated intermediate invariant. Establish the obligation inventory and coverage before concluding zero violations. A complete scoped empty inventory can establish an empty managed state. A partial read, missing receipt, inaccessible reader, or stale or contradictory observation leaves the relevant claim unknown. Absence over observed or open data requires a matching completeness receipt for the exact scope and cut. A closed modeled relation may prove absence within its declared domain. An invalid base yields a counterexample. An undecidable base yields its missing grounds. [Witnessed read completeness](witnessed-read-completeness.md)

Evaluate the base and each variant with the same pinned compiled rules and identical observation bytes and identities. Evaluate the entire signed delta before checking the effect boundary. Require fresh keys for adds and exact old-row matches for removes. Reject illegal row weights and conflicting writes before combining deltas. A cancellation must never hide competing actions. A hypothetical deletion cannot supply an observation that a dependent service stopped. Keep predicted violations in the speculative variant, separate from the real publication. Publication invariants keep their existing checks. The pack expressly identifies which invariants also hold at every intermediate boundary. [Snapshot differences](../edge/publisher/rezono_publisher/difference.py) · [Speculative evaluator](../rezono/src/evaluate.ts)

For independently submitted members, inspect the empty subset, the full batch and each other potentially completed subset. In each visible state, recheck the remaining members' positive matches, forbidden patterns and identities. Their residual deltas must still produce the same keyed effects under the same independently verified boundaries. This covers split success, reordered completions, lost replies and crashes between submits. For an adapter-proven indivisible effect, its public pre- and post-effect states are the visible boundaries. Incremental and batch recomputation must agree on rows and independently verifiable witnesses at every delta.

Two cases distinguish this policy from weaker checks.

- A listener and the protection it needs can produce a valid final state. The execution that exposes the listener first violates the intermediate invariant. Refuse the batch until existing protection is observed.
- Three structurally independent unit reservations compete for capacity two. Every singleton and every pair passes. The three-member subset exceeds capacity and must be refused. Include width three in the oracle.

### Deterministic selection

Use bounded relational joins over the complete finite candidate domain. Include singletons. Choose the largest certified batch among policy-equivalent alternatives, then choose the lexicographically least ascending tuple of distinct integer priorities declared by the pack. Prove there is no preceding certified alternative using the declared width, the full comparison domain, batch sizes, priorities and the reasons excluded alternatives failed. Report any missing or duplicate priority that affects choice. A pack decision must resolve competing desired outcomes before they can be treated as equivalent. `std-order.before` provides dependencies. Its optional rank alone cannot settle priority ties. Replay must give the same selection and proof under input permutation. No shortest-plan search is needed for these finite questions. [Order rules](../packs/std-order/rules/order.dl) · [Solver boundary](solver-proposals.md)

### Dispatch, readback and fixed point

Dispatch only the selected members for the certified run, base and cut. A changed base or cut requires a fresh evaluation. Durably claim each nonrepeatable plan hash before submit. A crash after the claim can leave no submit. A lost or uncertain reply consumes the attempt and holds its reservation until readback reconciles it using the same key. Keep outstanding effects reserved and exclude interfering work from later rounds. The first implementation may wait for the batch to settle. [Effect contract](../contracts/effect.yaml)

Use actual independent readback for completion, including for a successful submit. Recompute the next base from the readback and current cut. When actual and predicted rows disagree, retain both witnesses and derive drift. Complete scoped absence can establish a missing object. Timeout or incomplete coverage gives unknown. A newly observed invariant violation ends the certified chain and produces a finding. A correction is a separate checked plan. [Observed comparison rules](../packs/std-loop/rules/comparison.dl)

An unfinished goal reaches a fixed point when a complete relevant sweep establishes an empty certified frontier and no remaining producer, deferred safe candidate or pending operation can supply progress. Cite the missing or failed ground for every unfinished goal. A pending read or incomplete coverage leaves the result pending. An expired recorded deadline and an executor round limit are separate findings. Neither establishes absence of safe progress. [Fixed-point rules](../packs/std-loop/rules/fixed_point.dl)

## 3. Independent transition certificates

Use ordinary proofs for the base and speculative snapshots, linked by a transition certificate. Bind the certificate to the desired manifest, run, cut, compiled definition, base and variant identities, rule, identifying bindings, expected old rows, signed delta and effect identities. Include requirement witnesses, forbidden-pattern queries and their scope receipts, and the complete applicable integrity and invariant inventory with checkable zero-result evidence. The checker independently reapplies the delta and verifies the snapshot identities, preserved observation inputs, rule witnesses, scoped negations and aggregate contributor sets. A certificate does not carry authority from a boolean verdict alone. [Proof contract](../contracts/proof.yaml)

| Claim | Additional evidence |
| --- | --- |
| Individual safety | Base and variant witnesses, including the base witness for a removed conclusion and the variant witness for an added conclusion. |
| Batch safety and choice | Exact members, compatible writes, the combined delta, every visible partial certificate or an equivalent independently checked proof, residual effects and the complete selection comparison. |
| Wait from a violation | The violated invariant, its offending bindings and the change that caused it. Removing an in-use database cites the running consumer, its runtime dependency and the missing provider in the variant. |
| Wait from unknown evidence | The missing reader, scope and window, with any stale, partial or contradictory receipts. |
| Completion or fixed point | The actual same-run readback and event time for completion, or the closed goal and producer inventory, blockers and checked absence of possible progress. |

Apply existing proof visibility rules to the certificate and its grounds. A role must be able to read the supporting evidence before receiving a claim.

## 4. Platform acceptance

### Start from an empty managed scope

The opening fixture accounts for the runner's Kubernetes API, Cilium and Hubble, storage and any preinstalled admission resources with bootstrap observations. A complete inventory establishes that the declared managed scope starts empty and has no exposed managed listener. Preserve logical placement and lifecycle distinctions when projecting the platform onto the disposable cluster. [Disposable workflow](../.github/workflows/disposable-cluster.yml) · [Platform topology](../examples/platform/cluster-scenario.yaml)

| Progression in a prompt-readback replay | Evidence enabling the next actions |
| --- | --- |
| Prepare isolated namespaces and the router boundary. | Namespace identities and effective default-deny posture, with no published managed listener. |
| Install the needed Cilium policies, router allowances and admission bindings, and prepare independent storage. | Effective policy, exact rules, active bindings and bound storage. The rendered artifacts alone do not establish these facts. |
| Start protected runtime prerequisites such as DNS, time and the selected databases. | Selected placement, bound storage and usable paths. The fixture can start independent databases together and read their health separately. |
| Start identity and the services that depend on it. | `idp` needs healthy `db-idp` and DNS. `git` needs healthy `db-git` and identity. Confirm identity and time before starting `store`, and the required identity paths before the selected control-plane and secret services. The fixture bootstrap API has its own identity. |
| Start registry and GitOps where their desired providers are available. | Confirm object storage and identity for the registry. Confirm Git, identity and the selected control endpoint for GitOps. Read the target's reconciliation status before applying tenant workloads. |
| Admit dependent workloads, then publish eligible entry. | Confirm runtime, build and signing dependencies, healthy backends, effective network controls and required TLS. Verify policy with independent probes and Hubble. |

The pack supplies these dependencies from desired product demands, providers, placements and decisions. Different branches can advance at different speeds. Recorded round numbers are expected outcomes, never inputs to the executor. A shared router allowance remains while an authorized flow needs it. Preserve tenant and recovery isolation, current authorization scoped to the change, protection for every exposed endpoint and provision of each running consumer's runtime dependencies. Require decisive evidence for all scheduled network cases, observed completion of every declared goal and no unexpected terminal drift. Keep the intentional prohibited recovery flow and unsigned-component findings visible. An expected discrepancy cannot waive an intermediate invariant. [Platform flow rules](../examples/platform/rules/core.dl) · [TLS case](../examples/platform/acceptance/test_entry_tls.py) · [Recovery flow case](../examples/platform/acceptance/test_recovery_flow_delta.py)

### Restore a named management dataset during an outage

Before the outage, bind the named dataset to the exact captured copy, including its backup identity, source cluster, capture evidence and digest. Verify scope, age and eligibility against the governing decision. During the outage, record an independent management-unreachable probe and verify the recovery target's own control plane, credentials and direct data-plane access to storage. Every actual recovery dependency must remain available without the stopped management plane. A permitted route alone cannot establish that availability. If a required provider still depends on management, the evidence must yield a wait or a witnessed fixed point.

Reserve the exact eligible copy and isolated target, preserve the source and restore without granting active authority. Independently read the recovered bytes and match the run, trial, backup, recovery target, capture evidence and digest. Require distinct capture, trial and readback identities and a recovery cluster distinct from the source. Record the second independent management-unreachable observation after readback. To claim that management stayed down throughout, keep stop or fence evidence covering the interval. Two boundary probes alone establish the boundaries. A foreign run, reused evidence, wrong target, wrong copy or wrong bytes cannot complete the goal. [Backup decision](platform-management-backup.md) · [Capture and readback rule](../examples/platform/rules/management_restore.dl) · [Backup proof cases](../examples/platform/proof_cases/test_management_backup.py) · [Backup routes](../examples/platform/rules/management_backup_routes.dl)

This goal authorizes dataset recovery in isolation. Promoting replacement management to active authority is a separate acceptance question requiring exclusive authority, fencing and reconciliation probes. Management loss blocks changes to hosted application controls. Runtime availability follows its own evidence. [Outage rules](../examples/platform/rules/outage.dl)

## 5. Independent DPO oracle

Core owns a test-only AlgebraicRewriting oracle beside the existing Catlab migration oracle. Pin a compatible exact AlgebraicRewriting version and its resolved dependencies in the Julia test project and lockfile. Independently author typed attributed C-sets, base states, spans `L ← K → R` and negative application conditions. Supply the case to the oracle without Rezono's chosen match or expected result. Enumerate monic matches, compute the pushout complements and results, and compare the normalized keyed row deltas and preserved context. Compare the complete match and result sets up to identity-preserving isomorphism for fresh parts. [Catlab project](../compiler/tests/catlab/Project.toml) · [Catlab lockfile](../compiler/tests/catlab/Manifest.toml) · [Existing migration oracle](../compiler/tests/catlab/oracle.jl)

Cover create, delete, replace and move. Use typed incidence arrows so a surviving incoming arrow prevents deletion of a referenced object. Removing the dependent arrow in the same rewrite permits it. Reject forbidden aliasing under the monic policy. Exercise zero, one and multiple forbidden extensions and separately remove Rezono's scope evidence to require unknown. Transport independent matches through each other in both orders, preserving shared context and rechecking negative conditions. Exercise delete/use, duplicate create and rewrites that create a forbidden match for another member. Keep the capacity-three counterexample alongside these structural cases. Structural independence cannot establish the pack invariant. A mismatch blocks correctness.

Production uses typed row deltas and ordinary rules. Adopt a production rewriting engine only if a named acceptance question outgrows that design.

## 6. Separate formal round protocol

Loop owns `formal/Rounds.tla` and its separate formal verification. Model two runs, two workers, two cuts and a protection and exposure effect. Track confirmed and actual modeled state, certified batch and cut, pending members, durable claims, submits, observations and completion tokens. `Evaluate` freezes the frontier, `Claim` consumes the exact attempt and `SubmitOne` exposes individual effects. `Crash`, `LoseReply`, `Observe`, `CloseSweep`, `Reconcile` and `NextRound` cover interrupted execution and readback. Permit out-of-order and foreign-run observations and corrections. State fairness and environmental responsiveness separately from safety.

| Configuration | Required result |
| --- | --- |
| `Rounds.cfg` | Preserve `EveryVisiblePrefixValid`, `OnlyCertifiedDispatch`, `DoneHasCurrentMatchingObservation`, `AtMostOneSubmitPerNonrepeatableHash` and `NoFalseFixedPoint`, including crashes between visible members. |
| `RoundsTrustSubmit.cfg` | Violate `DoneHasCurrentMatchingObservation` when submit is treated as completion without readback. |
| `RoundsCombinedOnly.cfg` | Violate `EveryVisiblePrefixValid` when protection and exposure are admitted by their final state alone. |
| `EffectNoLock.cfg` | Preserve the separate single-attempt negative control. Disabling the claim must violate `AtMostOneSubmit` with two workers on one plan. |

Run TLC in the separate formal workflow on relevant changes. Each negative configuration must fail on its named invariant. Map every model action to the replay or adapter test that exercises it, marking actions with no implementation counterpart explicitly. A single-attempt model does not establish round safety.

## 7. Acceptance and ownership

The following independent cases guide the later test changes. Each case belongs to its named track. Platform records the two acceptance questions in `examples/platform/questions.yaml`. The recorded and live cases validate them through independent observations. The disposable cluster retains the `cluster` marker. Formal controls advance separately.

| Track and acceptance case | Evidence or prerequisite |
| --- | --- |
| Core · `test_step_variant_rows` | Hand-worked signed insert, replacement and deletion with unchanged observation data and batch/incremental parity. |
| Core · `test_transition_certificate` | Independent checker fixtures reject a missing invariant, forged zero, wrong cut and changed delta. |
| Core · `test_step_dpo_oracle` | Pinned Julia oracle compares the typed cases in section 5 with the row implementation. |
| Loop · `test_step_safety_reasons` | Supplied variants distinguish safe, false prerequisite, violated invariant and unknown coverage. |
| Loop · `test_batch_visible_prefixes` | Independent finite enumeration rejects exposure first and capacity overflow at width three and checks selection under permutation. |
| Loop · `test_safe_fixed_point` | A closed blocked frontier yields a finding. A pending producer, incomplete coverage or safe deferred candidate prevents it. |
| Loop · `test_certified_round_replay` | Variant, checker and selection components replay a chosen batch, lost reply, stale cut and later contrary readback. |
| Loop · `test_rounds_tlc_controls` | Separate formal verification checks the named controls and maps actions to replay cases. |
| Platform · `test_startup_transition_cases` | Authored cases exercise early exposure, removal of an in-use provider and missing coverage. |
| Platform · `test_restore_offline_dependencies` | Authored cases exercise independent recovery paths, management dependence and wrong bytes or trial. |
| Platform · `test_platform_safe_rounds_recorded` | Replay independent startup and recovery recordings after step bindings and certified replay are available. |
| Loop · `test_startup_safe_rounds_live` | Live disposable startup from verified empty scope through certified rounds to observed readiness and the deliberate findings. |
| Platform · `test_management_backup_restore_readback` | Reuse the existing matching-copy acceptance with a disposable recovery target and real observations on both outage boundaries. |
| Platform · `test_management_dataset_restored_offline` | Extend live readback with the dataset binding and sustained stop or fence evidence. |

## 8. Limits of the guarantee

The guarantee is inductive over the modeled visibility boundaries and scoped to the pinned observations, assumed adapter behavior and declared intermediate invariants. A successful certificate establishes neither unmodeled hazards nor future reachability. An observed contradiction requires new evidence and a new certified base. Keep final readiness, ordinary drift and deliberate test findings distinct from intermediate safety. Whole-run acceptance requires the two recorded and live scenarios above.

The step declaration's authored spelling belongs in a follow-up language decision. The row, scope, confirmation and invariant meanings here determine its contract.
