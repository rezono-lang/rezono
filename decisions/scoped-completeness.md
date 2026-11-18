# Require checked evidence of scoped completeness

A received row supports a positive claim. A conclusion that relies on an exhaustive read also needs evidence of which population the read covered. Use one `CompletenessReceipt` for scoped absence, final aggregates and complete sets of safety checks. Make verified coverage a positive premise of every conclusion that depends on it. [Project vision](../docs/vision.md) · [Rule and witness semantics](../docs/formal.md)

## 1. Receipt and authority

Define `CompletenessReceipt` alongside `Observation`. The receipt identifies a complete read at one cut. Individual observations continue to carry their own source position and event time. [Observation contract](../contracts/observation.yaml) · [Source contract](../contracts/source.yaml)

| Field | Required binding |
| --- | --- |
| `source` | The existing `Source` locator and position of the read being attested. |
| `issuer` | The identity that performed the read and the pinned declaration authorizing it to enumerate this population. |
| `scope` | The relation or query and its definition digest, with typed bindings for the population, partition and run where applicable. A changed filter or binding changes the scope. |
| `cut` | The immutable source revision, snapshot or log frontier. A time window also gives its axis, bounds, endpoint convention and the source position that establishes coverage through that boundary. |
| `inventory` | A pinned reference and SHA-256 of the expected member keys in canonical order, with independent evidence that these keys exhaust the scope. A member may be a row, node, log partition or obligation. |
| `content` | A pinned reference and SHA-256 of the canonical contents keyed by those members. Include each member's values, origins and terminal read evidence. Record a terminal empty result when a member returns no rows. |
| `id` | SHA-256 of the versioned canonical receipt body, excluding `id`. Use the shared canonical encoding and a fixed key order for the body and both referenced collections. |

Preserve schema types in keys and bindings. Use Rezono's canonical object member order and exact scalar spelling. Order the keyed inventories and contents by their canonical typed keys. Write SHA-256 digests as lowercase hexadecimal. Coalesce retries with identical content and evidence. Conflicting content for the same key invalidates the read. The inventory digest and content digest name distinct objects. [Canonical JSON and hashes](../canon/README.md)

A pack or protected admission policy declares the authoritative source, allowed issuer and enumeration procedure for each scope. A source reader can attest an immutable snapshot or bounded log read. For a finite modeled population, a checker can establish coverage by replaying the population from pinned inputs. A consumer can submit either kind of evidence. Admission verifies authority before accepting the receipt.

Resolve the expected inventory independently of the submitted results. Replay the pinned enumeration or verify the source's authoritative commitment. Require equality of the expected and covered member keys and verify the contents and terminal evidence for each member. A partition can answer while omitting one of its rows. The check must detect that omission through replay or the source commitment. Equal counts and a digest of the received subset cannot establish completeness.

Missing pages, gaps, lost events, conflicting final reports, inaccessible evidence or mismatched pins leave coverage unknown. An attested empty inventory is valid where the scope permits emptiness. A missing inventory leaves coverage unknown. A verified receipt can be replayed at its recorded cut. Each new cut requires its own evidence.

## 2. Shared rule interface

Put the rules in the fact-free standard pack `std-completeness`. Admission supplies the verified receipt and the exact authenticated read. `Source`, `Scope` and `Cut` identify their bound definitions and `Receipt` is the receipt digest. The two hash arguments identify the verified inventory and contents.

```prolog
complete(Source, Scope, Cut, Receipt) :-
    verified_receipt(Receipt, Source, Scope, Cut, InventoryHash, ContentHash).

absent_checked(Source, Scope, Cut, Key, Receipt) :-
    complete(Source, Scope, Cut, Receipt),
    in_scope_query(Scope, Key),
    !registered_match(Receipt, Key).
```

`in_scope_query` binds a typed key or pattern, including keys whose matching set is empty. `registered_match` is the lower-stratum lookup over the contents of the exact receipt. Admit the negative premise only after checking determinacy for that receipt and key. If an unknown value could match, preserve the unresolved lookup and derive no absence. A missing receipt leaves the conclusion unknown.

The witness binds the instantiated query, the positive `complete` row, the receipt and both digests. It records the negative `RowRef` at its stratum and snapshot. An aggregate witness also carries its group, position, contributor count and contributor digest, including for an empty group. The independent checker recomputes the lookup or aggregate over the certified contents. [Proof contract](../contracts/proof.yaml)

A verified complete snapshot of a closed modeled relation can supply the contents. Its population must come from pinned inputs and the checked rule closure. An open observation relation keeps its open world. A verified receipt supports absence of a matching registration within the specified scope and cut. An `@absence` annotation alone supplies no coverage. [Open world and named outcomes](../docs/compiler/rules.md#open-world-and-named-outcomes)

Source coverage and role authority are separate. Under explicit `std-access` semantics, a role needs witnessed `may_read_full` for the populations used by its negative or aggregate grounds, the underlying element rights and a readable proof. A partial reader sees neither the unsupported conclusion nor its hidden grounds. An authorized party may publish a separately sourced summary as a fact. [Witnessed read completeness](witnessed-read-completeness.md) · [Access model](../docs/vision.md#access)

## 3. Applications

### Rounds

Bind the expected sweep nodes to authoritative inventory. Keep interval, terminal report, gap and loss checks. Comparison needs a receipt that covers the actual token query and event time, with the existing latest-event and conflict checks. Removing a node and its result together must leave a gap in coverage.

`ready(run, step, reason)` requires membership in the selected batch of an independently verified transition certificate. Pin the desired manifest, compiled definition, run, cut, base, members, expected old rows, signed deltas and effect boundaries. Reconstruct the full obligation inventory from the definition and compare it with the check results. With the observed inputs fixed, reapply the deltas and check integrity and all applicable intermediate invariants at the base, final state and every permitted visible partial outcome. Recheck remaining matches, scoped blockers and residual keyed effects at each boundary. Missing coverage leaves a waiting obligation identifying the missing ground. A violation identifies the offending bindings. Completion still requires independent same-run readback. [Sweep](../packs/std-loop/rules/complete_sweep.dl) · [Comparison](../packs/std-loop/rules/comparison.dl) · [Readiness](../packs/std-loop/rules/ready.dl) · [Step safety](../packs/std-loop/rules/step_safety.dl) · [Safe transition rounds](safe-step-rounds.md)

### Build selection

Pin the run attempt, event, base and head commits, protected build engine commit and capture cut. Cover the complete changed path set, suite and test inventories, both endpoint manifest graphs, file dependencies and path-to-reader mapping. A path is readerless when its verified mapping has neither a direct reader nor a transitive reader. Retain that witness even when there is no job row. An empty selection for a nonempty diff needs a readerless witness for every changed path. When capture is incomplete, schedule full checks with a reason. Use the trusted CI suite universe if the captured suite inventory is incomplete.

Keep a case that deletes the only reader of a mapped source while keeping both the capture receipt and the mapped marker. It must select full checks. An independently verified readerless document remains the empty-selection control. [Build reconciliation](build-reconciliation.md) · [Selection rules](../build/rules/selection.dl)

### Month close

Pin both the completeness receipt and the price publication digest in the close decision. The receipt covers every intake partition for the declared population with `received_at < closed_at`, established by the immutable receipt-log frontier. Verify the complete read and replay the exact receipt identities, plan hashes and contents before allocating lines to half-open UTC service months. Publish the rational total only for a verified receipt. Unknown coverage leaves the close pending without a total. A verified empty contributing set yields zero.

In the April fixture, omitting the timely setup receipt while its key remains in the independent inventory leaves an apparent rental subtotal of `91/60`. The month must remain open. Restoring the receipt gives `47/20`. An observation received exactly at the cutoff can add a late finding without changing that total. [Month-close decision](run-closed-month.md) · [Replay](../run/closed_month.py) · [April fixture](../run/tests/test_closed_month.py)

### Checker state projection

For every descriptor the pinned definition requires, verify the descriptor and enumerate the independently archived source rows at the same epoch. Rebuild the relation from the evidenced `Value` and authenticated origin. Its key is `(subject, state, reason)` and its value is that origin. Compare both keys and values in both directions. Distinguish an explicitly empty snapshot from an absent artifact. Project an omitted slot only with a scoped absence proof and the applicable schema state rule. A required-slot declaration alone supplies no source state row.

Check the complete publication first. Then check each role against its separately authorized projection. The checker must identify a missing projection row when the engine also removes its dependent conclusions and witnesses but leaves the archived value and origin intact. [Projection checker](../checker/rezono_checker/state_projections.py) · [State-evidence cases](../compiler/tests/rezono/test_native_rule_state_evidence.py)

## 4. Independent round oracle

Two lanes initially serve. Replacing either lane has two externally visible actions, withdrawal followed by activation. Each lane goes from `old` to `offline` to `new`, and serves in the first and last states. The invariant requires at least one serving lane.

| Lane A | Lane B | Serving lanes |
| --- | --- | ---: |
| old | old | 2 |
| old | offline | 1 |
| old | new | 2 |
| offline | old | 1 |
| offline | offline | 0 |
| offline | new | 1 |
| new | old | 2 |
| new | offline | 1 |
| new | new | 2 |

An independent oracle enumerates all nine pairs that preserve each lane's local order. Each solo replacement passes at every boundary. The combined final state passes and the legal prefix `withdraw A, withdraw B, crash` fails. Reject a certificate that omits `(offline, offline)` even when every listed result passes.

Split the replacements at their visible effect boundaries. Once either withdrawal is visible, the other waits until readback establishes a serving lane again. A step may use only pre- and post-effect boundaries when a tested adapter guarantees indivisibility. [Effect boundaries](safe-step-rounds.md#2-certify-every-visible-state)

## 5. Acceptance

Freeze the receipt fields and rule signatures before staging separate tests. Give each test an independent inventory and source evidence, and exercise its ordinary checker, publication, replay or reporting entry point.

| Track | Test | Independent expectation |
| --- | --- | --- |
| Core, contract | `test_completeness_receipt_exact_inventory` | An attested empty read and reordered identical retries pass. Reject equal-count key substitution, omitted content inside a covered member, a different cut and an unauthorized issuer. |
| Core tests, language rules | `test_absent_checked_requires_readable_coverage` | A full reader gets witnessed absence for a verified empty lookup. Losing the receipt or full-read authority withholds the result. |
| Loop observations | `test_sweep_cannot_drop_expected_node` | An independently enumerated two-node scope stays incomplete after one node and its terminal report disappear from the submitted read. |
| Loop admission | `test_ready_requires_checked_batch_member` | A supplied positive check with an omitted obligation yields no readiness. A selected member of a valid current certificate can become ready. |
| Loop visibility | `test_overlapping_withdrawals_break_availability` | The nine-state oracle admits both solo replacements and rejects overlapping withdrawals, including a certificate omitting the failing boundary. |
| Loop, build | `test_mapped_path_requires_reader_inventory` | In a pinned Git fixture, a dropped path reader causes full checks and certified readerlessness permits an empty selection. |
| Run | `test_closed_month_requires_receipt_inventory` | The independent timely receipt set gives `47/20`. Omitting the setup receipt withholds a final total. |
| Core, checker | `test_state_projection_rejects_omitted_row` | The independent archive requires the row even after every copy and witness on the projection side is removed. |

An oracle mismatch blocks correctness until resolved against the semantics. A later independent observation can establish drift from a certified prediction. Keep the evidence for both. [Independent oracles](../docs/formal.md#11-independent-oracles)
