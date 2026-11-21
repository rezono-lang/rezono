---
decider: [language, core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: explain-repair
---

# Explanation question `repair` in `std-explain`: chase completion and costed choice

`std-explain` adds the computed explanation question **`repair`** ("what is the smallest change that makes this hold?"). When a declarative `require` obligation from [`decisions/language-requirements.md`](language-requirements.md) is violated, a reader should not have to translate a violation row back into a fact edit by hand. Instead, Rezono derives the smallest valid repair candidate, replays it locally through `suppose` ([`decisions/local-suppose.md`](local-suppose.md)), and verifies the resulting proof graph with `rezono_checker` before returning any proposal.

The design is split into two layers:

- **Layer 1 (chase completion, `extra`):** derives minimal additive repairs directly from `rezono 1` `require` declarations using the standard relational chase, marks unconstrained required slots explicitly as `unknown` (to be filled in), replays every proposal through `suppose`, verifies every proof fail-closed with `rezono_checker`, and refuses non-terminating (cyclic existential) requirements statically.
- **Layer 2 (costed choice via solver, post-Release 1):** extends `repair` to competing multi-candidate choices, retractions, and reassignments using [`decisions/solver-proposals.md`](solver-proposals.md) and origin-based mutability (`std-origin`, building on [`decisions/fact-origin-required.md`](fact-origin-required.md)).

---

## 1. The `repair` question in `std-explain` and `contracts/explain.yaml`

### Standard pack (`packs/std-explain/`)

[`packs/std-explain/questions.yaml`](../packs/std-explain/questions.yaml) defines `repair` alongside `gap`, `contrast`, and `consequence`:

```yaml
  # What is the smallest change that makes an unmet requirement hold: minimal additive chase
  # completion, replayed with suppose and verified by the checker. Computed.
  - term: repair
    start: present
    applies_to: {derivation: conclusion}
    steps:
      - trace: {direction: back, depth: all}
      - suppose: repair
    answer: repair
    limit: 50
```

- `packs/std-explain/messages/en.mf2` adds:
  - `explain.repair = Repair`
  - `explain.repair.question = {{What is the smallest change that makes {$element} hold?}}`
  - `explain.not_computed.chase_non_terminating = {{Not computed: requirement {$element} has a non-terminating chase cycle.}}`
  - `explain.not_computed.incomplete_evidence = {{Not computed: evidence for {$element} is incomplete; complete the sweep first.}}`
  - `explain.not_computed.not_additive = {{Not computed: {$element} cannot be repaired by adding facts alone.}}`
  - `explain.not_computed.observation_immutable = {{Not computed: observations cannot be changed by a repair.}}`
- `packs/std-explain/messages/nl.mf2` adds the corresponding Dutch entries:
  - `explain.repair = Herstel`
  - `explain.repair.question = {{Wat is de kleinste wijziging waardoor {$element} geldt?}}`
  - `explain.not_computed.chase_non_terminating = {{Niet berekend: eis {$element} heeft een niet-stoppende chase-cyclus.}}`
  - `explain.not_computed.incomplete_evidence = {{Niet berekend: gegevens voor {$element} zijn onvolledig; rond eerst de meting af.}}`
  - `explain.not_computed.not_additive = {{Niet berekend: {$element} kan niet alleen met aanvullingen worden hersteld.}}`
  - `explain.not_computed.observation_immutable = {{Niet berekend: waarnemingen mogen door een herstel niet wijzigen.}}`
- `compiler/rezono_compiler/pack.py` admits `answer: repair` in `ANSWERS` and `suppose: repair` in `composed` (allowed after a `trace` step from a `present` conclusion start), and `compiler/rezono_compiler/standard_packs.py` pins the updated `std-explain` pack hash.

### Explanation contract (`contracts/explain.yaml`)

[`contracts/explain.yaml`](../contracts/explain.yaml) extends the explanation schema without breaking existing questions:

- `AnswerShape` adds `repair` ("Minimal additive repair proposals derived from `require` declarations via the chase, replayed through `suppose` and verified by the checker.").
- `SupposeDelta` adds `repair` ("Minimal additive repair deltas derived by the chase from unmet `require` declarations, each replayed through `suppose` and verified by the checker.").
- `Answer` adds optional `repair: {range: RepairAnswer, inlined: true}` (always paired with `computed: true`, matching `contrast` and `consequence`).
- New classes in `contracts/explain.yaml`:
  - `RepairAnswer`:
    - `needed: boolean` (required): `true` when at least one unmet additive requirement needs a change; `false` when the requirement already holds (`known true`) or is `not_applicable`, or when `not_computed` explains why no repair can be computed.
    - `proposals: RepairProposal[]` (inlined list, deterministic order): verified minimal repair proposals; always empty when `needed` is `false`.
    - `cut: boolean` (required): `true` when proposal enumeration stopped at `limit`.
  - `RepairProposal`:
    - `delta: RezonoDocument` (required): a valid [`contracts/delta.yaml`](../contracts/delta.yaml) (`rezono.delta/1`) document holding the minimal additive changes.
    - `additions: RepairAddition[]` (inlined list, required): structured summary of each synthesized missing instance/row (`kind`, `key`, `key_unknown: boolean`, and `slots` mapping each declared slot to a `RepairSlotValue`).
    - `supposition: RezonoDocument` (required): the `rezono.supposition/1` result produced by replaying `delta` through `rezono_publisher.suppose` (including `manifest: p-local-...`, `rows`, and `withheld: null`).
    - `verified: boolean` (required): MUST be `true` on every emitted proposal (fail-closed; unverified proposals are never returned).
    - `witness: RezonoDocument` (required): the checker-verified [`contracts/proof.yaml`](../contracts/proof.yaml) (`rezono.proof/1`) proof proving that the target requirement evaluates to `known true` in the supposed manifest.
  - `RepairAddition`:
    - `kind: string` (required): snake_case kind or target relation name.
    - `key: string` (required): deterministic fresh placeholder key assigned for speculative replay.
    - `key_unknown: boolean` (required): `true` when the identifier is a freshly synthesized placeholder that an author must choose before committing to `main`.
    - `slots: RezonoDocument` (required): mapping from slot name to `{state: "known", value: ...}` for equality-constrained slots and `{state: "unknown", reason: "to_be_filled"}` for unconstrained required slots.

---

## 2. Layer 1: chase completion from `require`

### 2.1 Minimal additive derivation with witness

Every `rezono 1` `require` declaration ([`decisions/language-requirements.md`](language-requirements.md) §5) is a tuple-generating dependency (TGD) or counting TGD:

$$\forall \vec{k} \in D.\; P(\vec{k}) \;\longrightarrow\; \exists^{\mathrm{bound}}\, x \in Q.\; W(\vec{k}, x)$$

Given a requirement `<name>` and key tuple `k`:

1. **Already satisfied or not applicable:** If `<name>(k)` evaluates to `known true` or `not_applicable` (zero violation rows in `<name>_violation` for `k`), no repair is needed. `repair` returns `computed: true`, `repair: {needed: false, proposals: [], cut: false}`, without running `suppose`.
2. **Additive deficit:** When `<name>(k)` evaluates to `known false` and every violation row `(k..., clause, target, bound, observed)` in `<name>_violation` for `k` has a lower-bound deficit (`at_least:N` with `observed < N`, or `exactly:N` with `observed < N`), the chase derives the **minimal additive completion**:
   - For each violated clause `c_i`, synthesize exactly `deficit = N - observed` fresh instances of `target` (never more than `deficit`, and never touching existing satisfied clauses).
   - For each synthesized instance, bind every equality constraint in `W(k, x)` (such as `rack = r` and `bus = bus_a`, or `service = s` and `healthy = yes`) to its concrete value.
   - If inserting a new instance of `target` triggers another `require` declaration in the pack, close the candidate under cascading additive requirements until a fixpoint is reached (guaranteed finite by Section 2.4).
3. **Soundness guards (inherited from `language-requirements.md` and `local-suppose.md`):**
   - **`unknown` (`incomplete_read`, `open_world`, `no_value`):** NEVER triggers an additive repair. Returns `computed: true`, `not_computed: "incomplete_evidence"`, `repair: {needed: false, proposals: [], cut: false}`. An incomplete sweep requires completing the read, never inventing missing facts.
   - **`invalid` (conflicting inputs):** NEVER triggers an additive repair. Returns `computed: true`, `not_computed: "invalid_input"`, `repair: {needed: false, proposals: [], cut: false}`.
   - **Upper-bound violations (`at_most:N` with `observed > N`, or `exactly:N` with `observed > N`):** Cannot be satisfied by adding facts alone. Returns `computed: true`, `not_computed: "not_additive"`, `repair: {needed: false, proposals: [], cut: false}` (handled in Layer 2).
   - **Observation-layer targets (`layer: observation`):** Observations cannot change under an assumption ([`decisions/local-suppose.md`](local-suppose.md)). If a required target kind has bundle layer `observation`, Layer 1 returns `computed: true`, `not_computed: "observation_immutable"`, `repair: {needed: false, proposals: [], cut: false}`.

### 2.2 Missing required instances carry explicit `unknown` slots

Rezono never invents fake values (`""`, `0`, `"TBD"`) for missing data:

- Each synthesized record receives a deterministic fresh placeholder identifier (a labeled null, e.g. `fresh:<target>:<index>` that collides with no existing key of `target`) and is flagged `key_unknown: true` in `RepairAddition`.
- Every slot constrained by an equality in `W(k, x)` receives its concrete value in both `delta.changes[i].values` and `additions[i].slots[slot] = {"state": "known", "value": ...}`.
- Every remaining unconstrained required slot of `target` (for example, `serial: Text` on a missing `PowerSupply`) is **omitted** from `delta.changes[i].values` and explicitly reported in `additions[i].slots[slot] = {"state": "unknown", "reason": "to_be_filled"}`. Under [`contracts/delta.yaml`](../contracts/delta.yaml), an absent required slot has four-state value `unknown` (`no_value`), never `""` or `0`.
- During speculative `suppose` replay of a chase repair delta, totality violations caused **exclusively** by explicitly declared chase-unknown placeholder slots on freshly inserted repair records are downgraded from `red` to `warning`, using the same exact per-key check as `unset` in `edge/publisher/rezono_publisher/suppose.py` (`_may_downgrade_totality`). Any other totality violation (including pre-existing violations or non-placeholder missing slots) still blocks `suppose`, and committing a repair to `main` still blocks until an author supplies concrete identifiers, slot values, and origins.

### 2.3 Mandatory `suppose` replay and `rezono_checker` verification (fail-closed)

No repair proposal is ever emitted directly from static chase synthesis alone:

1. **Compiler chase module (`compiler/rezono_compiler/repair.py`):**
   - `check_chase_termination(model)`: static weak-acyclicity check over all `require` declarations in `model` (Section 2.4).
   - `derive_repairs(model, derived_rows, requirement: str, key: tuple[str, ...], *, limit: int = 50) -> dict`: runs `check_chase_termination(model)` first, checks soundness guards, and produces candidate minimal additive repairs (`delta` + `additions`).
2. **Publisher verification module (`edge/publisher/rezono_publisher/repair.py`):**
   - `repair(pack_dir, store, base_manifest: str, role: str, requirement: str, key: tuple[str, ...] | list[str], *, limit: int = 50) -> dict` (and CLI entry point `rezono-repair`, parallel to `rezono-suppose`).
   - Enforces the same `may_read` role access discipline as `rezono_publisher.suppose.suppose` and never mutates `pack_dir` on disk.
   - For every candidate delta from `derive_repairs`:
     1. Replays `delta` via `rezono_publisher.suppose.suppose(pack_dir, store, base_manifest, role, delta, ...)` to publish the speculative manifest `p-local-<12 hex>-<epoch+1>` next to `base_manifest` and obtain the checked difference (`rezono.supposition/1`).
     2. Independently verifies the supposed manifest's proof of `<requirement>(key)` with `rezono_checker.check.check(proof, supposed_manifest, checker_rules, read_bytes)`.
     3. Confirms that:
        - `report["valid"] is True` and `report["findings"] == []`;
        - `<requirement>(key)` evaluates to `known true` in the supposed manifest;
        - the violation row in `<requirement>_violation` for `key` is removed (`weight == -1` in the supposition difference);
        - no invariant check is `red`, and `supposition["withheld"] is None`.
   - **Fail-closed:** if `suppose` blocks (`publish.Blocked`, `difference.Blocked`, `views.Blocked`), `rezono_checker` reports any finding or `valid: False`, or `<requirement>(key)` still does not hold, the candidate is discarded and never returned.

### 2.4 Chase termination: refusal of cyclic existential requirements

To preserve Rezono's guaranteed-termination invariant, the chase MUST NOT run on requirement sets that can generate unbounded chains of fresh instances.

`rezono_compiler.repair.check_chase_termination(model)` applies the standard, decidable **weak acyclicity** criterion over all `require` declarations in a pack:

1. Construct the directed **position dependency graph** `G` whose nodes are `(kind, "id")`, `(kind, slot)` for each kind and slot, and `(relation, col)` for each `Bool` relation target:
   - **Normal edge `p -> q`:** whenever a trigger position `p` is copied unchanged to a target position `q` by an equality in `W(k, x)` (e.g. `ps.rack = r` adds `(rack, "id") -> (power_supply, "rack")`).
   - **Special (existential) edge `p -*-> q*`:** from every trigger position `p` to every existentially generated position `q*` of an `exists` clause — in particular, the newly synthesized instance identity `(target, "id")` and every unconstrained slot `(target, slot)` receive a special edge from `(trigger_kind, "id")` (and from each trigger parameter position of a multi-key `over` requirement).
2. Check whether `G` contains any directed cycle that traverses **at least one special (existential) edge**:
   - **Cycle with a special edge (refused):** raises `ChaseTerminationError` (a subclass of `pack.CompileError` with diagnostic code **`chase_non_terminating`**, naming the offending requirement(s) and kind cycle). Examples:
     - Direct self-cycle: every `Node` requires a distinct backup `Node` (`require node_has_backup(n: Node) exists b: Node where b != n and b.backup_of = n`) creates `(node, "id") -*-> (node, "id")`.
     - Mutual cycle: every `PrimaryUnit` requires a `StandbyUnit` and every `StandbyUnit` requires a `PrimaryUnit` creates `(primary_unit, "id") -*-> (standby_unit, "id") -*-> (primary_unit, "id")`.
   - **No cycle through a special edge (accepted):** returns `{"terminates": True, "requirements": [...]}`. Acyclic requirements (such as `Rack -> PowerSupply`, or a bounded chain `Rack -> PowerSupply -> FeedPort`) always terminate in finitely many steps.
3. **Runtime bound:** As defense in depth, `derive_repairs` and `repair` also enforce a strict finite step/candidate cap (`limit`, bounded by the profile) and fail closed if reached.

---

## 3. Layer 2: costed choice via solver (post-Release 1)

Layer 1 handles minimal additive completion when each missing pattern is determined by `require` alone. After Release 1, Layer 2 extends `repair` to problems where multiple valid repairs exist or where adding facts alone is insufficient:

- **Solver boundary ([`decisions/solver-proposals.md`](solver-proposals.md)):** When repairing upper-bound cardinality violations (`at most N`, `exactly N` with `observed > N`), reassigning shared capacity, or resolving competing requirements requires searching a combinatorial space, `repair` may request candidate deltas through [`contracts/offload.yaml`](../contracts/offload.yaml). As fixed in `decisions/solver-proposals.md`, the solver has zero authority over acceptance: every proposed repair delta still passes through `suppose` and `rezono_checker` for independent witnesses, and global minimum-cost optimality remains a claim of the solver.
- **Origin-based mutability and cost (`std-origin`):** Building on [`decisions/fact-origin-required.md`](fact-origin-required.md) and [`decisions/local-suppose.md`](local-suppose.md), a future `std-origin` vocabulary classifies every fact's origin to govern what Layer 2 may propose to change:
  - **Observations** (facts from collectors, tools, queries, or `observation`-layer kinds): **never** changed by a repair. Reality cannot be edited away; operational remediation must run through authorized safe steps ([`decisions/language-safe-steps.md`](language-safe-steps.md)) and independent readback.
  - **Decisions and design choices** (`decide` blocks, `Decision` records, authored design/configuration facts): **mutable** in Layer 2 repairs at declared change costs, subject to pack authorization and independent proof verification.
  - **Vendor publications and external norms:** immutable unless superseded by a newer pinned publication.

---

## 4. Tests (`extra`)

Two strict `extra:` behavioral tests in `compiler/tests/rezono/test_explain_repair.py` specify Layer 1:

| Test | Waits for | What it verifies |
| --- | --- | --- |
| `test_repair_chase_proposes_missing_power_supply_with_unknown_and_verifies_via_suppose` | `compiler/tests/rezono/test_language_requirements.py--test_requirement_violation_witness_cites_trigger_and_missing_pattern` | `std-explain` declares `repair` (`contracts/explain.yaml` valid); for a `Rack` with only `PowerSupply` B under `require rack_dual_power`, `repair` proposes adding `PowerSupply` A with an explicit `unknown` (`to_be_filled`) placeholder slot and `key_unknown: true`, replays the delta through `suppose`, verifies the resulting proof fail-closed with `rezono_checker`, and leaves the pack untouched on disk; counterexample: a `Rack` with both A and B returns `needed: false` and zero proposals. |
| `test_repair_chase_refuses_cyclic_existential_requirement_and_accepts_acyclic` | `compiler/tests/rezono/test_language_requirements.py--test_lower_requirement_to_rules_ir` | Direct self-cyclic existential `require` (every `Node` requires a distinct backup `Node`) and mutual cyclic existential `require` (`PrimaryUnit <-> StandbyUnit`) are refused with `ChaseTerminationError` / `chase_non_terminating`; counterexample: an acyclic multi-hop chain (`Rack -> PowerSupply -> FeedPort`) is accepted with `terminates: true`. |

---

## 5. Considered

- **Returning raw chase candidates without `suppose` and `rezono_checker`.** Rejected: a synthesized record can violate another invariant, fail a schema check, or fail to discharge a non-equality filter in `W(k, x)`. Every emitted proposal must carry a checker-verified witness from a real `suppose` replay.
- **Fabricating default values (`""`, `0`, synthetic serial strings) for unconstrained required slots.** Rejected: violates Rezono's explicit-unknown invariant ("missing is never zero or empty string") and risks leaking placeholder text into real proposals. Unconstrained required slots stay explicitly `unknown` (`to_be_filled`) until an author fills them in.
- **Allowing cyclic existential `require` rules with only a runtime step counter.** Rejected: a step counter turns a non-terminating specification into silent truncation or arbitrary partial repairs. Static weak-acyclicity refusal makes termination decidable, transparent, and fail-closed, while the runtime `limit` stays as defense in depth.
- **Mutating observations in Layer 1 or Layer 2 repairs.** Rejected: contradicts [`decisions/local-suppose.md`](local-suppose.md) and Rezono's provenance model ([`decisions/fact-origin-required.md`](fact-origin-required.md)); observations report the world and cannot be edited away by a repair.
