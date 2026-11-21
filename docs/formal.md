# Formal foundations

Rezono describes a state with an attributed schema, computes changes to it as weighted differences, derives conclusions by stratified rules, and carries data between schemas by typed mappings. These four descriptions concern the same rows at different boundaries. The mathematical models below explain what the compiler and checker are intended to preserve. Each section identifies where the repository supplies a concrete implementation or test.

## 1. Schema and state: ologs and ACSets

A schema presents a small category C. Its kinds are objects, its arrows name typed references, and its path equations identify composites that must agree. Attribute types also specify how values are interpreted. An instance assigns a set to each kind and a mapping to each arrow, respecting identities, composition and equations. An attributed C-set (ACSet) includes the data values. Two paths that the schema equates must agree on every element where the equation applies.

The compiler represents kind membership as rows such as `item(id)` and attribute values or references as rows such as `item__group(id, value)`. A required slot adds a totality obligation, a scalar slot adds functionality, and a reference requires an existing target of the correct kind. A multivalued slot can instead describe a relation. Give a link its own kind when it has identity, attributes or additional endpoints. Subkind rows retain the identity they have in the ancestor table. The generated integrity relations make violations observable. If V(X) denotes those violations on state X, the state satisfies the checks when V(X) is empty. [Schema and instance checks](compiler/schema-operations.md), [integrity test with failing controls](../compiler/tests/test_generality.py).

An authored Rezono module can already lower kinds, attributes and references, and enumeration values into the same schema model that the compiler uses for LinkML input. That includes checked scalar and optional slots. The supported construct inventory is wider than this core and reports reader and lowering coverage separately. Richer native declarations, such as standalone units, parameter and reason declarations, lack a complete lowering path. Native rule signature linking alone does not make the native rule pipeline complete. LinkML remains the interchange form. [Kind and slot lowering](rezono/publication.md#51-kinds-and-slots), [enum lowering](rezono/publication.md#52-enums), [reader and lowering coverage](rezono/language-coverage.md).

## 2. Deltas and incrementality: DBSP

A weighted relation is a finitely supported map from rows to integers. A row insertion has weight +1 and a retraction has weight −1. Weights add, and zero-weight rows disappear. An update is the retraction of the old row plus the insertion of the new row. Summing a stream of such deltas recovers the sequence of snapshots. Taking successive differences recovers the deltas, using the empty snapshot before the first step.

Write I for integration (running sum), D for differentiation (difference from the preceding step), and Q for a snapshot query applied pointwise. Its incremental form is QΔ = D ∘ Q ∘ I, so I ∘ QΔ = Q ∘ I. This equation states a testable requirement for the integrated result. It does not require the runtime to recompute every snapshot. Linear primitives act directly on changes. For a bilinear join the change has three terms, dA ⋈ B, A ⋈ dB and dA ⋈ dB, given the previous A and B. Distinctness depends on the accumulated weight. Recursive fixed points may use iteration streams inside a time step.

The batch result and the integrated change stream must agree on the same input history. Applying an inverse delta restores the original rows, within the domain of the operation. The real incremental oracle exercises this boundary with Feldera and a separate DuckDB batch evaluation. [Incremental proof test](../examples/test_platform_incremental_proof.py).

## 3. Rules: Datalog with provenance

A positive rule program derives its least fixed point. In a stratified program each stratum reaches a fixed point before later strata may use its completed relations in negation or aggregation. Safety, termination and world checks constrain the accepted program. A closed relation can establish absence at a complete snapshot. An open relation needs explicit evidence for the scope where absence was checked. [Rule semantics and completeness](compiler/rules.md#open-world-and-named-outcomes).

A witness identifies a rule, its variable bindings and its premises. A positive premise points to the row used. A negative premise binds the particular absent tuple and the snapshot or scope in which its absence was checked. An aggregate premise binds the group and its contributing rows, including the relevant aggregate position. Empty groups and ties need the same evidence discipline as other groups. A checker must compare these grounds with independently evaluated rule instances. Valid individual witnesses establish support for the rows that are present. A closure check also guards against omitted derivable rows. [Proof contract](../contracts/proof.yaml), [checker tests](../checker/tests/test_proof.py).

The dependency graph can be read as a hypergraph with all premises required for one firing and alternative firings for one conclusion. Where-provenance ends the walk at a cited base row. Derivation provenance explains how those rows combine. A tree chosen for reading can rank its premises by depth and use a deterministic tie-breaker. It still represents one alternative. In a recursive derivation, cyclic support without a grounded derivation establishes no conclusion. A role may read a conclusion only with the grounds it needs. A full-relation read check is needed where a negative or aggregate ground depends on unseen rows. [Witness alternatives cases](semantics/witness-alternatives-cases.yaml), [role publication requirements](../decisions/role-publication-requirements.md), [fact sources](compiler/import.md#provenance-per-fact).

For positive queries a provenance semiring models alternatives by addition and co-occurring premises by multiplication. That interpretation alone does not represent negative evidence, completeness or arbitrary aggregate choices. Enumerating all proof trees can also be prohibitive. Integer change weights describe multiplicity in a dataflow, while witness identity describes which derivation was used. Freshness, access and explanation can ask different questions of the same grounded evidence.

## 4. Between layers: functorial data migration

A structure-preserving map F from schema C to schema D lets a D-instance be read at C by restriction along F. Write this operation Δ_F. Its left and right adjoints, Σ_F and Π_F, are defined by the corresponding colimits and limits. The left migration can combine values and impose identifications. The right migration assembles compatible families and can produce joins. This accounts for why a mapping may forget information, identify values, or require compatibility.

The implemented operations use checked row migrations. The lossless contract is a statement about the operation and its admissible states, including lineage and retained sources where applicable. A model of a schema map does not by itself establish that a particular migration is invertible. Rezono compares forward and reverse row multisets for the supported oracle cases. Categorical query languages are a semantic reference for migration, and Catlab is the independent implementation used for the repository's migration comparison. LinkML remains a supported interchange form. [Schema operations and migrations](compiler/schema-operations.md).

## Design: theories, views and colimits

A theory pack declares vocabulary, equations and rules without base facts of its own. A domain can interpret that vocabulary by binding kinds and paths. The bounded executable profile checks and lowers a view to ordinary rules. Typed unions, richer path composition and general theory satisfaction remain a broader design. The satisfaction law asks whether interpreting an instance along the schema map and testing a sentence gives the same truth value as testing its translation. The repository tests selected theories and executable views. [Theory design and executable profile](compiler/schema-operations.md#design-theories-and-views), [theory satisfaction tests](../compiler/tests/test_theory_satisfaction.py).

A colimit can compose presentations that share a schema fragment. Shared vocabulary imported through a pinned closure, an explicit assertion that two elements denote the same thing, and the combination of proposed changes are different operations. A common spelling alone gives no identification. Element identity remains (kind, id) unless a typed mapping or explicit evidence provides an identification.

A reading of a publication, such as a graph or an ordered table, interprets a selected structure. In the sense of algebraic semiotics, the mapping has preservation obligations for the particular reading, such as edge incidence, order, containment, scope and access. The view boundary does not assert that every presentation of a model preserves its whole theory. [Publication and readings](rezono/publication.md).

### One structure

Place and sight are instances of this structure, not features beside it. [One structure decision](../decisions/one-structure-space-and-readings.md).

- Space is a theory with two models. `std-space` declares places, their parts through the `part_of` of `std-part`, and the eight relations of region connection as axioms, without facts. Its symbolic model is the part-of tree alone. Its geometric model, `std-geo`, has integer coordinates on a declared grid with exact predicates. A theory morphism maps the one into the other, so geometric containment implies `part_of`. Its satisfaction is tested like that of the other theories, with a reversed binding as the failing control.
- Anchoring is a view. A domain binds its kinds to places with an ordinary view, so an anchor is a derived row with two times, a state, a source, a witness and access, and is maintained incrementally. No contract has an anchor field.
- Spatial membership takes the four states. A point or cell inside a region is known true and outside it known false. On the boundary, or not yet decided by the cells, it is `unknown` with the reason `straddles`. No overlap anywhere is `absent` only with a complete sweep as its witness, and contradictory classifications of one place are `invalid`. There is no separate rough-set or egg-yolk model.
- A reading is a morphism whose losses are published. It binds a role's publication to marks and is declared in a pack's channels; a theory's channels give its default readings to every domain bound to it. Per reading and role the checker measures what the reading preserves, such as order, containment and coverage, as exact counts with the elements that break it, and the report is published beside the reading. Every measure warns and none blocks: a report says what a picture keeps, not that it is understood.

## 5. Plans: DPO rewriting

Double-pushout (DPO) rewriting describes a change by a span L ← K → R. The match of L locates the old pattern. K is the interface preserved by the change, and R specifies the resulting pattern. With monic matches, the pushout complement expresses the deletions that can be made without leaving dangling references. The second pushout attaches R at the surviving interface. Negative application conditions rule out specified matches, and independence of two matches is the condition under which their applications can commute.

For a concrete match m and its extension m′, the candidate row delta has the shape −m(L ∖ K) + m′(R ∖ K). Conjunctive queries supply candidate matches, and a closed anti-join can express a negative condition when the application has that evidence. Rezono currently validates and applies typed row deltas and observes the results of ordered steps. A DPO engine, comparison against AlgebraicRewriting and proofs of general commutation belong to the design. [Delta contract](../contracts/delta.yaml), [proposal and publication semantics](rezono/publication.md).

## 6. Calculation, unknown and money

Calculations use exact integers and fractions. Money in a specified currency is represented in whole minor units, with conversion rounded at the declared boundary. For half-away-from-zero rounding, a tie at a half moves outward from zero. Allocation by largest remainder assigns a total in whole units, then distributes the remaining units by remainder with a fixed tie order. Exact fractions and explicit rounding points let a checker recompute the result from its leaves.

Missing, inapplicable and invalid values carry an explicit state and evidence or a reason as appropriate to the operation. Whether a value persists through an expression depends on that expression's reading of the states. In a rule, only an allowed positive reading of a known calculation selection becomes a premise. The calculation witness records the arithmetic and grounds, and the checker uses exact arithmetic independently of the production SQL helpers. [Calculation contract](../contracts/calc.yaml), [value cases](semantics/value-cases.yaml), [calculation checker tests](../checker/tests/test_calc.py), [calculation values in rules](compiler/rules.md#calculation-values-in-rules).

An aggregate of the rule IR folds the states of its members by the format of its program. In `rezono.rules/1` (`rezono 0`) the checker's fold blocks on `invalid`, is strict in `unknown` and does not count `not_applicable`: a sum skips it. In `rezono.rules/2` (`rezono 1`) `count`, `sum`, `min` and `max` are strict in all three states, `invalid` before `unknown` before `not_applicable`, as Appendix A.3 of the [expressions](rezono/expressions.md#appendix-a-truth-tables-normative) requires, and an author leaves members out only with an explicit filter. So the checker's fold takes the format of the program it checks. [Aggregate spelling and four-state folding](../decisions/language-rezono-1-aggregate-spelling.md#2-four-state-folding).

## 7. Time, epochs and sealing

Validity time describes when a row applies, and knowledge time describes when the evidence became known. A validity interval is half-open, so the end of one interval can be the start of another. The calculation selection can use declared temporal roles. The distinction between a source retrieval time, a fact's validity and an execution timestamp matters for replay.

An epoch groups an input and its results at a concrete boundary. The manifest pins the artifacts a reader checks, and the coverage for a negative or aggregate ground must match that epoch. The runtime can move through multiple parts before it publishes a manifest. A barrier is required so that a result from one epoch is never joined with incomplete output from another. A seal commits to the selected rows by canonical hash when its completeness and acceptance conditions hold. A seal differs from an epoch identifier and from a transport acknowledgement. [Manifest](../contracts/manifest.yaml), [seal and pipeline partition](compiler/rules.md#seal).

## 8. Offloads

An offloaded step would pass a particular unit and input to a solver or planner, and bring back a result as a fact through admission. Its hash covers the input and parameter data, model, solver version, limit and fixed seed. An output for an earlier input is stale. A current input without an admitted result is pending. A valid result must carry enough evidence for the receiving boundary to check its claimed status.

The offload contract distinguishes `optimal`, `best-found` and `infeasible`. A time-limited run may produce a different candidate on the same pins. Replay uses the recorded admitted result. Duration is telemetry. A step cannot depend on its own result to form its input. Rule witnesses establish the declared checks on a candidate, while the solver remains the source of its optimality or exhaustiveness claim. The general worker and solver integration remain design. [Offload contract](../contracts/offload.yaml), [freshness contract](../contracts/freshness.yaml), [solver proposal decision](../decisions/solver-proposals.md).

## 9. The whole

The model gives a common set of obligations across the pipeline.

- Normalize and validate the typed input before deriving a result.
- Run the same rules on an ordinary snapshot and on a scenario, and preserve which facts were observed and which were assumed.
- Require equality between the reconstructed incremental result and the batch result for the same inputs, including the evidence compared by the relevant oracle.
- Produce canonical artifacts and a deterministic key order under the declared representation. Where a rename is meant to be an equivalence, compare results after transporting along the rename.
- Restrict by the reader's access before emitting rows, grounds or a rendering. A reading of the output is a projection of the checked publication.

Write Φ for the compiled snapshot computation. Its incremental form should satisfy ΦΔ = D ∘ Φ ∘ I. A scenario delta δ and its inverse −δ restore the original fact state under the update rules. Computed answers carry the premises that justify them, so a reading can trace the affected rows back to their grounds. These obligations concern typed, exact, validated inputs. They do not establish that arbitrary changes commute or that the compiler and engines are correct without independent tests.

For a typed view v* of a domain in a theory, the design additionally asks whether Φ_theory ∘ v* = v* ∘ Φ_domain on the supported vocabulary and query fragment. That obligation concerns the two ways of computing the same answer. The bounded satisfaction tests, access checks and incremental comparisons address particular parts of it.

Search is a further design for explanations, such as finding a small repair, a set of missing facts that could justify a conclusion, or a configuration that meets a goal. A solver can propose such a change. The ordinary scenario evaluator recomputes it and the independent checker verifies the resulting grounds before review. A proposed repair may change decisions and other permitted inputs. It may not rewrite observations to reach the target. [Solver proposal decision](../decisions/solver-proposals.md).

The vocabulary of homotopy type theory gives names to three expectations here. An equivalence transports answers through a lossless change. A `same-as` assertion gives evidence for identification. Proof relevance keeps the premises of each derivation available even when a reading selects just one. These expectations are expressed through the data and proof contracts. The repository does not use a general proof assistant to establish them. [Identity theory](../packs/std-identity/pack.yaml), [project vision](vision.md), [publication checks](rezono/publication.md).

## 10. Protocols (TLA+)

State and query semantics describe what result is correct. A temporal model describes the steps through which a runtime could publish that result.

- An epoch model identifies which part produced a row and which readers received it. It requires at-most-once delivery per producer, reader and epoch and complete delivery before the manifest becomes publishable.
- An effect and claim model can express exclusivity for a resource, ownership through a transition, and release after an observed result.
- A lifecycle model can require a green epoch for publication, prevent publication of a reverted change, and prevent repeating an effect whose result is unknown. It must verify that an effect still uses the intended input hash. Progress to a terminal state depends on explicit fairness assumptions for plugin responses.

The repository checks four finite configurations with TLC. Epoch delivery and transactional publication check completeness. Effect locking checks that a retained claim admits at most one submission. Claim cleanup checks whether a lease, generation and open pull request make removal safe. Each configuration has a deliberately broken companion that must fail on its named invariant. The broader lifecycle above remains design.

The protocol guide maps model actions to any direct runtime replays and records the gaps. Nearby effect tests cover prerequisites and follow-up behavior, including approval matching and status reconciliation. The model runs establish the properties of the configurations under their stated assumptions. Runtime conformance still needs direct replay of the model actions. [Protocol models and configurations](../formal/README.md), [runtime replay coverage](../formal/README.md#what-ties-a-model-to-the-code), [pipeline contract](../contracts/pipelines.yaml).

## 11. Independent oracles

An oracle computes an expected answer independently in a test. A difference must be resolved against the governing semantics. A reference source records what a person, another system or an observation reported. A difference with a reference source is drift with evidence. The independent proof checker also runs in production to verify a publication. That check has a different role from the test oracles.

The component CI paths below can run on pull requests, merge groups, pushes to main and manual dispatch. The selected components determine which of those test suites run. [CI workflow](../.github/workflows/ci.yml).

| Check | Comparison | Where it runs |
| --- | --- | --- |
| Canonical bytes | Canonical JSON vectors compare against an independently pinned RFC 8785 implementation. [Vectors](../canon/tests/test_vectors.py). | Canon component CI. |
| Integrity | Planted violations and valid controls exercise the generated integrity checks. [Tests](../compiler/tests/test_generality.py). | Compiler component CI. |
| Rules | The pinned Soufflé harness compares relation sets from selected generated and authored rule programs. [Harness](../compiler/tests/souffle.py), [source tests](../compiler/tests/test_souffle_source.py). | Compiler and examples component CI. |
| Explanation | Soufflé compares selected trace results and gap prefix computations. [Trace tests](../compiler/tests/test_trace.py), [gap tests](../compiler/tests/test_gap.py). | Compiler component CI. General question-oracle coverage is not built. |
| Witnesses | The checker consumes the program, rows and premises independently of the evaluator. Tests include valid proofs and malformed or missing evidence. [Tests](../checker/tests/test_proof.py). | Checker component CI. The publication path also invokes independent proof verification. |
| Change streams | Feldera runs the compiled pipelines incrementally and compares them with a separate batch evaluation on DuckDB: the conclusions of every example pack at each fact state, and the witnesses of generated programs and of one platform rule, which the checker also verifies. [Rules comparison](../examples/test_feldera_rules.py), [generated programs](../compiler/tests/test_rules_properties.py), [incremental proof test](../examples/test_platform_incremental_proof.py). | Scheduled nightly at 02:17 UTC on main, and by manual dispatch. [Feldera workflow](../.github/workflows/feldera-oracle.yml). The nightly schedule has no green run on main yet: [Feldera oracle disagrees on main](https://github.com/rezono-lang/rezono/issues/314). |
| Migrations | Catlab compares forward and reverse row multisets in supported operations. [Comparison](../compiler/tests/catlab/compare.py). | Matching pushes to main and manual dispatch. [Catlab workflow](../.github/workflows/catlab-oracle.yml). |
| Graph rewriting | The typed step matcher enumerates double-pushout matches and row deltas over keyed rows. Its oracle test compares them with independently authored match and delta sets, and with the pinned AlgebraicRewriting 0.5.0 oracle when `REZONO_DPO_JULIA` names a Julia executable. [Step matcher](../compiler/rezono_compiler/step_dpo.py), [oracle test](../compiler/tests/test_step_dpo_oracle.py), [Julia project](../compiler/tests/catlab/dpo/Project.toml), [decision](../decisions/dpo-rewrite-boundary.md). | Compiler component CI with the authored sets. No workflow sets `REZONO_DPO_JULIA`, so the AlgebraicRewriting comparison runs only by hand. A general DPO engine and proofs of commutation remain design. |
| Calculations | A Python fraction reference computes exact values, rounding and states independently. [Reference](../compiler/tests/calcoracle.py), [calculation tests](../compiler/tests/test_calc.py). | Compiler component CI. |
| Protocols | Pinned TLC checks four passing configurations and verifies the named invariant violation in each of their four deliberately broken companions. [Model guide](../formal/README.md). | Pull requests that change `formal/**` or the formal workflow. The job checks the exact proposed head. [Formal workflow](../.github/workflows/formal.yml). |
| Admission expressions | cel-go evaluates the hand-authored admission cases with explicitly typed request, object and parameter environments, beside Rezono's rendered CEL, and both are asserted against independently stated answers. [Oracle decision](../decisions/k8s-admission-oracles.md), [cel-go harness](../k8s-admission/oracles/cel/main.go), [tests](../k8s-admission/test_standalone_cel.py). | Admission component CI. |
| Admission policies | The upstream Kubernetes apiserver admission policy evaluator and matcher load complete policy and binding manifests offline, with typed fixtures and an in-memory parameter store, so binding failures count too. Server-side dry-run requests on the disposable cluster are the end-to-end oracle. [Apiserver harness](../k8s-admission/oracles/apiserver/main.go), [tests](../k8s-admission/test_offline_apiserver.py). | Admission component CI. The dry-run cases run in the [cluster workflow](../.github/workflows/disposable-cluster.yml). |
| Cluster network | Hubble records the destination-side verdict of each probed flow in a closed sweep of the fixture cluster. It is compared with the socket probe and the nftables verdict as an independent witness of what the derived network policy allowed. [Hubble sweep](../loop/cluster/network_hubble.py), [flow evidence](../loop/tests/flow_evidence.py), [network pairs test](../loop/tests/test_live_network_pairs.py). | Disposable cluster with Cilium and Hubble enabled. [Cluster workflow](../.github/workflows/disposable-cluster.yml), [decision](../decisions/shared-disposable-cluster.md). |
| Delivery timing | Plain Python recomputation of delivery waiting seconds and completion timestamps from recorded loop observations, independent of the `std-loop` delivery status rules. [Status times](../loop/tests/status_times.py), [delivery timing tests](../loop/tests/test_status_times.py). | Loop component CI. |
| Domain references | Plain Python recomputations that share no code with the compiler: the subsidy rules, award and ledger seal ([reference](../examples/subsidy/reference.py)), the healthcare allowance slice ([reference](../examples/zorgtoeslag-slice/reference.py)), the platform's derived relations and its tenant, firewall and cluster scenarios ([relations](../examples/platform/oracle.py), [tenant requests](../examples/platform/tenant_oracle.py), [firewall](../examples/platform/firewall_oracle.py), [cluster](../examples/platform/cluster_oracle.py)), and fragments of the loop's rules ([loop oracle](../loop/tests/loop_oracle.py)). | Examples, compiler and loop component CI. Some tests call a reference directly; others compare the outputs it recorded under `expected/` or in `oracle-rows.json`. |

The project vision requires the batch and incremental engines to agree on conclusions and on witnesses ([vision](vision.md#proof)). Today Feldera's conclusions are compared for every example pack, but its witnesses only for generated programs and for one platform rule. Two red tests state the rest: the rule witnesses of the subsidy pack at each fact state ([rule witness parity](../examples/test_rule_witness_engine_parity.py)), and the rows and witnesses of the calculations ([calculation parity](../examples/test_calculation_engine_parity.py), [decision](../decisions/feldera-calculation-parity.md)). Neither runs on the live oracle yet.

Oracle coverage is specific to the declared inputs and observed outputs. Compare sets when the semantics admits several proof choices or equivalent plans, multisets when the differences include multiplicity, and exact bytes when the format promises canonical encoding. Use generated cases as well as fixed examples. Keep a failing control where it establishes that the oracle can distinguish the failure under test. Ship only the production artifacts and permitted runtime dependencies. [Working rules](../AGENTS.md).

## References

- David I. Spivak and Robert E. Kent, *Ologs: A Categorical Framework for Knowledge Representation*.
- Evan Patterson, Owen Lynch and James Fairbanks, *Categorical Data Structures for Technical Computing*.
- Mihai Budiu, Tej Chajed, Frank McSherry, Leonid Ryzhyk and Val Tannen, *DBSP: Automatic Incremental View Maintenance for Rich Query Languages*.
- Krzysztof R. Apt, Howard A. Blair and Adrian Walker, *Towards a Theory of Declarative Knowledge*.
- Todd J. Green, Grigoris Karvounarakis and Val Tannen, *Provenance Semirings*.
- David I. Spivak, *Functorial Data Migration*.
- Joseph A. Goguen and Rod M. Burstall, *Institutions: Abstract Model Theory for Specification and Programming*.
- Joseph A. Goguen, *An Introduction to Algebraic Semiotics, with Application to User Interface Design*.
- David A. Randell, Zhan Cui and Anthony G. Cohn, *A Spatial Logic Based on Regions and Connection*.
- Hartmut Ehrig, Karsten Ehrig, Ulrike Prange and Gabriele Taentzer, *Fundamentals of Algebraic Graph Transformation*.
- Leslie Lamport, *Specifying Systems: The TLA+ Language and Tools for Hardware and Software Engineers*.
- The Univalent Foundations Program, *Homotopy Type Theory: Univalent Foundations of Mathematics*.
