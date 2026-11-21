---
decider: [core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: publish-founded-witnesses
---

# Publish every founded witness of a conclusion

Today the publisher keeps one chosen witness per derived row (`edge/publisher/rezono_publisher/access.py`, `choose`), and [contracts/explain.yaml](../contracts/explain.yaml) describes `Answer.witnesses` as "the chosen witness of each conclusion on this page". A viewer or reviewer inspecting a conclusion that holds by two independent rules or substitutions can therefore see only the single chosen witness, cannot tell whether a premise is required by every proof of the conclusion, and cannot navigate between alternative proofs.

Following [decisions/one-structure-space-and-readings.md](one-structure-space-and-readings.md) §4 ("The proof graph is data that rules read"), founded alternative witnesses and load-bearing premises are **not** consumer-specific fields computed in ad-hoc publisher or gate code. They are **derived relations over the published witness graph**, derived by Rezono rules and verified by the checker like any other rule derivation, and projected onto [contracts/explain.yaml](../contracts/explain.yaml) (`Answer.witnesses` and `AnswerStep.load_bearing`).

## 1. Founded versus cyclic alternatives

Alternative support follows the exact semantics worked out in [docs/semantics/witness-alternatives-cases.yaml](../docs/semantics/witness-alternatives-cases.yaml) and verified by [checker/tests/test_alternatives.py](../checker/tests/test_alternatives.py):

- For a role `R`, let `usable(R)` be the epoch's ground witness instances whose premises hold in the epoch, whose positive base premises `R` may read, and whose negated or aggregated relations `R` reads in full.
- A witness instance `a` in `usable(R)` with conclusion `r` is **founded for `R`** if and only if `r` is derivable in the least fixpoint of `(usable(R) \ {b : conclusion(b) = r}) ∪ {a}` — that is, `a` gives `r` a finite, acyclic proof tree using only `usable(R)` without relying on `r` itself.
- Every other witness instance in `usable(R)` for `r` is **cyclic** (for example the self-loop `reach_step(a,a,a)` in `finite-alternatives-on-a-cycle`, `reach_step(a,a,b)` in `alternative-through-its-own-row`, and `p_q(a)` / `q_p(a)` in `role-left-with-only-mutual-support`).

**Rule:** Only founded witnesses belong to the derived relation `founded_witness` for role `R`. Cyclic alternatives are never published and never appear in `Answer.witnesses`.

## 2. Deterministic ordering and per-conclusion cap

For each derived row `r` visible to role `R`, the founded witnesses `W_R(r)` are ordered in a single deterministic, total order, deduplicated by `canonical_sha256(w_without_iri)`:

1. **Chosen witness first (index 0):** the existing `choose` witness (least height/rank in `usable(R)`, then least `(rule_id, binding values)`) is always first, so single-witness consumers reading `witnesses[0]` remain unchanged.
2. **Remaining founded witnesses:** ordered by `(height(w), rule_id, canonical_bindings_json, canonical_sha256(w_without_iri))`, where `height(w)` is `1 + max(height(p) for positive derived premise p of w, default 0)` in `usable(R)`.

**Cap:** To keep every proof piece within `MAX_PIECE = 64 KiB` (`edge/publisher/rezono_publisher/proof.py`), a publication publishes at most **64** founded witnesses per conclusion in the order above. When `|W_R(r)| > 64`, the first 64 founded witnesses are published and the conclusion's `AnswerNode` carries `witnesses_truncated: true`. When `|W_R(r)| <= 64`, `witnesses_truncated` is omitted. Truncation is never triggered by witnesses outside `usable(R)`.

## 3. Canonical witness IRIs

Every founded witness carries its canonical witness IRI under the publication schema's `base`, as defined in [decisions/publication-conclusion-addresses.md](publication-conclusion-addresses.md) §2:

```text
<base>witness/<H(witness)>
```

where `<H(witness)>` is `canonical_sha256` of the witness without its `iri` slot (64 lower-case hex digits). The checker verifies `iri == canonical_witness_iri(schema, witness_without_iri)`, and the gate serves `iri` verbatim without recomputing it.

## 4. Relations over the witness graph: rules derive, checker verifies, gate reads

In line with [decisions/one-structure-space-and-readings.md](one-structure-space-and-readings.md) §4 and [decisions/code-does-not-decide.md](code-does-not-decide.md), the role's published witness graph (usable witness instances and their premise edges) is data that Rezono rules read to derive two relations per role `R`:

1. **`founded_witness(conclusion_rel, conclusion_key, witness_iri)`:** the founded witness instances of `usable(R)` (excluding cyclic alternatives), ordered with the chosen witness first.
2. **`load_bearing(conclusion_rel, conclusion_key, premise_rel, premise_key, how)`:** holds for a conclusion `r` with non-empty `W_R(r)` and premise `(p, how)` if and only if `(p, how)` occurs in **every** founded witness `w ∈ W_R(r)` (no founded witness of `r` in `W_R(r)` omits `(p, how)`). In particular, when `|W_R(r)| == 1`, every premise of that single witness is load-bearing; when `|W_R(r)| >= 2`, a premise omitted by any alternative founded witness is not load-bearing.

Boundary of responsibility:

- **Rules over the witness graph** derive `founded_witness` and `load_bearing` per role `R`.
- **The checker** verifies those derivations against the role's snapshots and proof graph (refusing any cyclic witness with `cycle` and any disagreeing projected `load_bearing` flag with `load_bearing_mismatch`).
- **The gate (`edge/gate/src/ask.ts`)** **only reads** the checked witness-graph projection into `Answer.witnesses` (`AnswerWitness.iri`) and `AnswerStep.load_bearing`. The gate never computes `load_bearing`, never filters cyclic witnesses at request time, and never synthesizes witness IRIs outside what was checked.

## 5. Role-scoped zero-leak (`role-with-a-hidden-alternative`)

In `role-with-a-hidden-alternative` (`facts: [edge(a,b), edge(b,a)]`, `reads: [edge(b,a)]`), the complete epoch has two founded witnesses for `near(a,b)` (`near_in(a,b)` and `near_out(a,b)`), while the restricted role `R` has `W_R(near(a,b)) = {near_in(a,b)}`:

- Role `R` receives **only** `near_in(a,b)`.
- **Non-interference (zero count leak):** every byte and field published for role `R` in the two-witness world (where `edge(a,b)` exists but is hidden from `R`) is **identical** to what is published for `R` in the one-witness world (where `edge(a,b)` does not exist at all) — no hidden-alternative counter, no placeholder witness, and no `witnesses_truncated` flag caused by hidden alternatives.
- **`load_bearing` is strictly relative to `R`:** for `R`, `edge(b,a)` has `load_bearing: true` (it is required by every proof in `W_R(near(a,b))`), revealing nothing about whether an unreadable alternative exists in the complete epoch.

## 6. Contract (`contracts/explain.yaml`) and recorded fixture

- [contracts/explain.yaml](../contracts/explain.yaml) projects the derived witness-graph relations onto `Answer`:
  - `AnswerWitness` (`is_a: Witness`) carries optional canonical `iri`, and `Answer.witnesses` projects every distinct founded witness from `founded_witness` for each conclusion on the page (chosen witness first).
  - `AnswerNode.witnesses_truncated` records when a conclusion hit the per-conclusion cap of 64 (never set for role-hidden alternatives).
  - `AnswerStep.load_bearing` projects the derived `load_bearing` relation onto each premise step (`true` when load-bearing for the role, `false` when an alternative founded witness omits it).
- `tests/fixtures/slip` carries at least one conclusion with at least two distinct founded witnesses so that downstream reader-parity recordings (such as Cartouche's `fixtures/10-slip-reader-answers.json` for `m1-slip-all-witnesses`) exercise multi-witness answers directly from a published store.

## Alternatives considered

- **Compute `founded_witness` or `load_bearing` in ad-hoc publisher/gate code for one consumer.** Rejected: conflicts with [decisions/one-structure-space-and-readings.md](one-structure-space-and-readings.md) §4 and [decisions/code-does-not-decide.md](code-does-not-decide.md); the proof graph is data that rules read and the checker verifies.
- **Expose a `hidden_alternatives` count to restricted roles.** Rejected: leaks the existence and count of unreadable base facts in `role-with-a-hidden-alternative`.
- **Publish cyclic alternatives with a `cyclic: true` marker.** Rejected: cyclic derivations are not valid proofs and would break the checker's acyclic proof guarantee.
