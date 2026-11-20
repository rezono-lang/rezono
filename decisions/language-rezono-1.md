---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-rezono-1
---

# Rezono 1: one derivation form as the first released language

`rezono 1` is the language of the first public release, with **one derivation form** (`derived`). `rezono 0` remains the internal workbench and keeps its existing syntax, semantics, and canonical printed form unchanged ([language reference §4b](../docs/rezono/v0.md#4b-language-version-and-deprecation)). Existing pack rule files convert **once**, directly from `.dl` or embedded `rules` blocks to `rezono 1`, rather than twice through `rezono 0` native rules.

This decision adopts and finalizes the design explored in [the first-release proposal](../docs/rezono/first-release-proposal.md), repairs ten technical errors and gaps found against the codebase, settles the effect on prior language decisions, and specifies the intended semantic differences for migrating `examples/platform/rules/core.dl`.

## 1. Fixed invariants and scope

Four constraints hold for every part of `rezono 1`:

- **Feldera remains the target incremental engine**, alongside DuckDB for batch/publication and Soufflé as an independent test oracle for the non-rational fragment.
- **Every program terminates.** Unbounded recursion, general arithmetic inside recursion (beyond the existing bounded-counter profile), and `min` or `max` inside recursion remain refused.
- **No built-in `best` or `first` over sets.** Choosing a winner over a set must remain explicit in the pack's candidate inventory, exclusions, and tie policy. (Static row-order `table first` remains explicit in the authored text.)
- **Symbols remain symbols.** `?`, `*`, `+`, `..<`, `@`, `-`, and `_` keep their symbolic form with no keyword synonyms introduced beside them.

### What ships in `rezono 1` vs later vs refused

| Construct | Decision | Rationale |
| --- | --- | --- |
| Schemas (`kind`, `extend`, `enum`, `unit`, `world open/closed`, `inverse`, refinements), facts (`fact`, `decide`, `assume`, dated facts), versioned `param`, `check`/`warn`/`require`, `reason`, `rounding`, `@` source citations, `means` sentences | **In `rezono 1`** | Core declarative surface; schemas, facts, parameters, and existing calculations carry forward unchanged from `rezono 0`. |
| Unified `derived` (single-key properties, multi-key module declarations, `Bool` sets, `T*` sets, functional `T` / `T?` over closed domains, `.one()`, `unless`, `version` with `valid`/`known`/`replaces`, `table` under `unique`/`first`/`collect`) | **In `rezono 1`** | Replaces the split between `rule` and `derived` with one domain-facing construct. |
| Method-form filtering and counting (`.where(pred)`, `.count(pred)`, relation-as-tuple-set with unambiguous bare column names) | **In `rezono 1`** | Removes positional wildcards, outer parentheses, and redundant `it.` prefixes while staying strictly inside the method form (`v0.md` §2). |
| `example` blocks with CI coverage warning `W109`, and two-knowledge-date comparison (`ask ... as known D1` vs `as known D2` reusing `rezono.turns/1`) | **In `rezono 1`** | Makes every pack self-testing and shows exact change impact before an amendment is approved. |
| Period shorthand (`valid 2026` -> `2026-01-01..<2027-01-01`, `valid 2026-03` -> `2026-03-01..<2026-04-01`) and digit grouping (`€ 38_520`, `2_400_000`) | **In `rezono 1`** | Unambiguous lexical/desugaring shorthands with zero semantic cost. |
| Generated syntax-highlighting grammar from `rezono/src/`'s Ohm grammar, and canonical formatter (`rezono fmt` backed by `rezono/src/print.ts`) | **In `rezono 1`** | Keeps highlighting in lockstep with the reader and gives every pack one canonical layout. |
| Literate law-text modules (using `fragment_sha256` in [`contracts/source.yaml`](../contracts/source.yaml)), declarative `role` blocks, `during`/`in` version axes, generic `theory`/`view`, custom `literal` types, effect classes (`computes`/`reads`/`transacts`/`writes`), `norm`, cross-pack exceptions (`exception ... of other.Target`), bounded search (`W110`), large editor features (context lenses, inline live example values, margin coverage, change-impact review view, prose reading view) | **After first release** | Additive extensions that can land once core packs, access/review rights, and prose normalization settle. |
| `table priority` decision-table policy | **Refused in `rezono 1`** | Silently breaking ties by the declaration order of an output enum makes reordering an enum silently change outcomes. Stays as built in `rezono 0`; in `rezono 1`, refused with `R028` and **`table first`** as the hint (ordered `unless` blocks remain the alternative outside tables). |
| Leading dot for element lookup (`.pred`) | **Not adopted** | [`docs/rezono/expressions.md`](../docs/rezono/expressions.md#5-name-resolution) §5 already resolves bare names on the element first and flags outer collisions with `R011` (disambiguated by `it.name` or an explicit binder such as `extend s: Service`). |

Because `rezono 1` is the first publicly released language, the external stability and phased-deprecation promise of [`docs/rezono/v0.md`](../docs/rezono/v0.md#4b-language-version-and-deprecation) §4b starts at `rezono 1`. `rezono 0` carries no long-term external support commitment once repository packs migrate.

## 2. One derivation form (`derived`)

Every derivation in `rezono 1` uses `derived`:

- **Key placement:**
  - **One kind key** -> derived property inside `kind K` or `extend K` (or `extend s: K` when naming the subject binder).
  - **Two or more keys** -> module-level `derived name(k1: T1, k2: T2, ...): R`. No artificial wrapper kind is ever invented for n-ary relations.
- **Result types and semantics:**
  - **`Bool`:** plain set relation. Every succeeding derivation keeps its own independent proof; stratified positive recursion is permitted; no extra state or reason columns are added.
  - **`T*`:** set-valued derivation yielding every derived member for a key (no uniqueness conflict; positive recursion permitted).
  - **`T` or `T?` (functional value with state):** for every key in its declared closed domain:
    - exactly one distinct value yields `known(v)` with its witness;
    - two or more distinct values yield `invalid` with a reason code and **every candidate value and its proof as witness** (never a silent pick);
    - zero values yield `unknown` with a reason code (such as `no_value`), or `not_applicable` (`n/a`) when the declared type is `T?` or an explicit guard is inapplicable.
- **Mandatory finite closed domain (`over`):**
  - Single-key functional derivations on `kind K` / `extend K` use `K` as their domain.
  - Multi-key functional derivations MUST declare a finite base or lower-stratum `Bool` domain relation via `over D(k1, ..., kn)`. A Cartesian product of kinds (such as `Service × Function`) is rejected at compile time to prevent unbounded incremental state materialization.
- **Set-to-functional conversion (`.one()`):**
  - `S.one()` over a closed set `S: T*` yields `known(v)` when `|S| = 1` (witnessed by the single member plus `count = 1` and `contributors_sha256`), `unknown no_value` (or `n/a` when the declared type is `T?`) when `|S| = 0`, and `invalid multiple_values` carrying every distinct member and its proof as conflict witness when `|S| > 1`.
- **Uniform modifiers:** ordered and sibling `unless` blocks, `version` blocks (`valid`, `known`, `replaces`), `table` blocks (`unique`, `first`, `collect`), `means "..."`, and `@ source#locator` work uniformly on `derived` declarations, reusing core reason codes (`exception_conflict`, `versions_overlap`, `no_row_applies`, `no_value`, plus `multiple_values`).
- **Publication conflict policy:**
  - **Rule-structure contradictions always block publication (`conflict_policy = block`, automatic invariant):** unresolved `versions_overlap`, sibling `unless` clashes (`exception_conflict`), and overlapping `table unique` rows.
  - **Data-multiplicity conflicts from `.one()` (`invalid multiple_values`) publish as findings by default (`conflict_policy = publish`)** on `partial` derivations (the default per `v0.md` §5d): the functional derivation emits `(key..., "invalid", "multiple_values")` with every candidate as witness, downstream `Bool` derivations reading its value (`d(k) = v`) require `state = "known"` and emit no false positive tuple, and checks or diagnostic views can test `d(k) is invalid` directly. A pack that wants data multiplicity conflicts to block publication writes `check` / `require` (e.g. `check unique_provider: not (needs(a, f) is invalid)`) or declares the derivation `total`.
- **Guarding `unless` without masking `invalid`:** because `is` always evaluates to `true` or `false` (`v0.md` §7b), an `unless` guard that should forward both `known` and `invalid` writes `unless not (chosen(a, f) is n/a) then chosen(a, f)` rather than `unless chosen(a, f) is known`, which would silently mask a conflict in `chosen`.

## 3. Effect on prior decisions

Existing `rezono 0` decisions stay in force for `rezono 0` modules and packs. For `rezono 1`, this decision supersedes, narrows, or extends five prior decisions as follows:

1. **[`decisions/language-native-rules.md`](language-native-rules.md):**
   - Stays in force for `rezono 0` (`rule ... when ...` in `rezono.module/3`); the existing `rezono 0` native-rule chain stays green as the workbench base.
   - Superseded for `rezono 1` by unified `derived` in `rezono.module/5`. Both design objections in `language-native-rules.md` remain satisfied: multi-key derivations stay module-level declarations with explicit typed keys (no wrapper kinds) and `Bool`/`T*` derivations preserve multiple independent proofs; `Bool` derivations stay plain sets with unchanged arity and proofs, and only non-`Bool` functional derivations carry `(state, reason, value)` over their declared domain.
2. **[`decisions/language-tables.md`](language-tables.md):**
   - Stays in force for `rezono 0` (including `table priority` as already built and tested).
   - For `rezono 1`, `table unique` and `table first` lower through the co-located functional derivation IR (`rezono.rules/2`) and `table collect` lowers through set-valued `T*` derivations rather than emitting 6–11 separate Datalog relations per value; **`table priority` is refused in `rezono 1` (`R028`, hint: `table first`)**.
3. **[`decisions/language-calculations.md`](language-calculations.md):**
   - Stays in force for `rezono 0` and legacy `calc/*.yaml` files.
   - Reconciled accurately (see Section 5, item 7): in `rezono 0`, `decisions/language-calculations.md` refuses `unless`, decision tables, state tests, sets, and aggregates in `rezono.calc/1` with `R050`; [`decisions/language-exceptions.md`](language-exceptions.md) lowers ordered `unless` blocks into `rezono.calc/1` definitions with `overrides`, while decision tables lower through `compiler/rezono_compiler/rezono_table.py` into `rezono.rules/1` (never through `rezono.calc/1`).
   - For `rezono 1`, those `R050` refusals are superseded: single-subject calculations, multi-key functional derivations, `unless`, `version`, `table`, state tests, and set aggregates lower uniformly through `rezono.rules/2` (see Section 5, item 6).
4. **[`decisions/language-readable-rules.md`](language-readable-rules.md):**
   - Stays in force for the shorter module header defaults and `means` / `@` on rules; both carry forward into `rezono 1` (where redundant defaults become `R028` and `linkml:types` is always implicitly imported, as scheduled there).
   - The two candidates left open in `decisions/language-readable-rules.md` — single-key derived properties inside `kind`/`extend`, and simpler method-form filtering/counting/summing (`.where(...)`, `.count(pred)`, relation-as-tuple-set) — are **adopted** for `rezono 1`.
5. **[`decisions/language-safe-steps.md`](language-safe-steps.md):**
   - The three `rezono 0` safe-step building blocks (`insert_row` in `suppose`, `step`, `invariant intermediate within`) continue to be built in `rezono 0` (`rezono.module/4`). A `step` lowers to a valueless match relation (`CompiledStep.match_relation`), which remains a `Bool` relation in `rezono 1`.
   - Platform packs convert their steps once, together with their rules, to `rezono 1`.
   - **What a `step` in `rezono 1` may read from a value-bearing (functional) derivation `d`:**
     - **In `when`:** may read a strictly lower-stratum functional derivation `d` positively for a known value (`d(k) = v`, requiring `state = "known"` and carrying `d`'s proof into the step match witness), or test its state positively (`d(k) is known`, `is unknown`, `is n/a`, `is invalid`) when `d`'s domain is closed and complete under the round's observation cut (carrying the state row and its witness). Reading `d(k)` in a value position when its state is `unknown`, `n/a`, or `invalid` never produces a step match.
     - **In `forbid <pattern> within <scope>`:** both `<pattern>` and `<scope>` remain direct `Bool` or base relation calls (not functional derivations), because scoped absence requires a complete key inventory. To forbid a condition involving a functional value, write a lower-stratum `Bool` relation or a state test in `when`.
     - **In `effect` (record keys, slot values) and `confirm` (`reader` arguments, `token`):** every expression referencing a functional derivation `d(k)` must require `d(k)` to be `known` (either bound positively in `when` or enforced by the compiler adding `state = "known"` to the step's match relation). An `unknown`, `n/a`, or `invalid` value can never be written into an effect delta, used as a record key, or passed as a confirmation token.
     - **In `invariant intermediate within <coverage>`:** written on `derived ...: Bool` derivations in `rezono 1`; the violation derivation may read lower-stratum functional derivations (value or state) under the same closed-domain stratification rules, while `<coverage>` remains a `Bool` or base relation.

## 4. Underlying IR, witnesses, checker, and engines (`rezono.rules/2`)

Pure desugaring of `rezono 1` functional derivations into `rezono.rules/1` + `rezono.calc/1` does not suffice: `outcome` in `rezono.rules/1` is restricted to one 1-column base kind and three states (`known`, `unknown`, `not_applicable`), naive table-style Datalog desugaring multiplies views by 6–11× per value (increasing pipeline count and cross-pipeline traffic), `rezono.calc/1` is single-subject/single-phase and numeric/Boolean-only, and conflict witnesses must carry every competing candidate rather than a single pair of row numbers.

`rezono 1` therefore extends the rule IR additively as **`rezono.rules/2`** (while `rezono.rules/1` remains valid for `rezono 0`):

- **Functional relation role (`contracts/rules.yaml`):**
  - Keep `role: derived` unchanged for `Bool` and `T*` set relations.
  - Add `role: functional` carrying: `key` (1+ typed columns), `domain` (mandatory name of a base or strictly lower-stratum `Bool` derived relation whose key columns match `key`), `value` (one typed column: `string`, `integer`, `rational`, or `boolean`) with co-located `state` (`known`, `unknown`, `not_applicable`, `invalid`) and `reason`, `conflict_policy` (`block` for rule-structure contradictions vs `publish` for `.one()` multiplicity conflicts), and ordered precedence/version/candidate rules strictly in a higher stratum than `domain` and outside any recursive component.
  - Replace the single-cut `partition_at_calc` with per-derivation stratification across `derived` and `functional` relations: cycles through any functional derivation, negation, or aggregation remain refused (`not_stratified` / `R009`), while acyclic interleaving (`Bool` recursion -> functional A -> `Bool` B -> functional C) is permitted.
  - **Access boundary unchanged:** `may_read` and `may_read_full` stay strictly in the `Bool` / base relational layer (`compiler/rezono_compiler/pack.py` and `checker/rezono_checker/rules.py` refuse any dependency of `may_read` or `may_read_full` on a `functional` derivation or `calc` selection) so `checker/rezono_checker/access.py` keeps its independent trust boundary.
- **Witnesses (`contracts/proof.yaml`):**
  - `known(v)`: winning clause/version/candidate plus absent higher-precedence guards; for `.one()`, the single candidate plus the candidate-group digest (`count = 1`, `contributors_sha256`).
  - `unknown(reason)` / `not_applicable`: domain key plus cause (empty candidate group `count = 0`, absent active version, or upstream non-known state row).
  - `invalid(reason)`: every competing distinct candidate and its proof (group digest plus candidate rows, resolved on demand or from a materialized candidate view).
- **Independent checker (`checker/rezono_checker/`):**
  - Generalize `outcome_total` and `outcome_state` from 1-column base kinds to any declared `domain` relation (single- or multi-key).
  - Verify for every domain key that `state` matches the candidate set (`count = 0` -> `unknown`/`not_applicable`, `count = 1` -> `known` matching the unique value, `count > 1` -> `invalid` with all distinct candidates matching the conflict witness) and reject publication if any `conflict_policy = block` relation contains an `invalid` row.
  - Verify that `may_read` and `may_read_full` never depend on a `functional` derivation.
- **Three engines (honoring the five Feldera rules):**
  1. **State after recursion, never inside:** functional views are never emitted inside `DECLARE RECURSIVE VIEW`.
  2. **Closed named domain:** every functional view `LEFT JOIN`s its declared finite `domain` relation (never a Cartesian product of kinds).
  3. **`Bool` stays a plain set:** `Bool` derivations emit plain set views with zero state columns or conflict views.
  4. **Co-located `(key..., state, reason, value)` view:** both **DuckDB** (`CREATE OR REPLACE TABLE`) and **Feldera** (`CREATE MATERIALIZED VIEW`) emit one combined view per functional derivation (reusing `calc_sql.DUCKDB_MACROS` / `udf/udf.rs` for exact rational columns; deterministic path projections such as `Service.zone` need only a `LEFT JOIN` without `GROUP BY`; only `conflict_policy = block` adds one tiny invariant check view `WHERE state = 'invalid'`).
  5. **Feldera calculation parity first:** before emitting `rezono 1` functional views on Feldera, compare all current `rezono.calc/1` states, reasons, and witness steps on Feldera against DuckDB and the checker across the examples.
  - **Soufflé (test oracle only):** inside `compiler/tests/souffle.py`, lower the non-rational fragment of each functional derivation to plain Datalog relations (candidate relation + `count` + `(key..., state, reason, value)` projection) and compare against DuckDB and Feldera without adding views to Feldera pipelines.

## 5. Ten codebase corrections and resolved gaps

Each of the ten issues identified against the initial proposal is resolved directly against the repository:

### 1. The 64-view budget is per pipeline, not per module

`emit.MAX_VIEWS = 64` (and `engine.view_budget` / `engine.build_memory_mb` in deploy profiles) bounds **each Feldera pipeline**, not each author module. In `compiler/rezono_compiler/rules_split.py`, `partition()` automatically cuts a rule program across multiple pipelines (`rules-1`, `rules-2`, …) in dependency order without being constrained by module boundaries. Only an indivisible **recursive core** (a strongly connected component of mutually recursive derived relations) exceeding the pipeline budget blocks compilation (`rules_split.TooBig`). Even a single non-recursive relation above the budget compiles in a pipeline of its own with an `over_budget` warning (`rules_split.over_budget`).

Therefore, naive table-style Datalog desugaring (6–11 views per value) is not rejected because "a module cannot fit 64 views"; it is rejected because **more views cost more pipelines**, which adds Rust compilation work, `export__out` tagged-union views, inter-pipeline relay traffic, and incremental memory. Co-locating `(key..., state, reason, value)` into one view per functional derivation keeps pipeline count and cross-pipeline exports low.

### 2. Equal view count does not mean equal compile or runtime cost

Matching the raw view count of `examples/platform/rules/core.dl` (33 views today: 30 derived relations + 3 materialized witnesses `flow`, `newest_day`, `providers`; vs an estimated 27–33 views in `rezono 1`) does **not** imply equal compile memory, build time, or runtime cost. A functional view does more work than a plain `Bool` set view:

- **Deterministic projection functional view** (e.g. `Service.zone`, `Service.cluster`): performs a `LEFT JOIN` from the closed `domain` to the slot/relation chain and synthesizes `(state, reason, value)` with `CASE` — no `GROUP BY` or distinct-count state.
- **Candidate-aggregating / precedence functional view** (e.g. `needs`, `chosen`, `Product.newest_day`, `Service.runs`, `flow_from_step`, versioned or `unless`/table derivations): performs `LEFT JOIN` over `domain`, `GROUP BY key` with `COUNT(DISTINCT val)` / `MIN`/`MAX`, short-circuit precedence/version selection, and exact-rational UDF calls (`udf/udf.rs`) when rational arithmetic is used.

**Profile view kind and weights (`compiler/rezono_compiler/emit.py`, `rules_split.py`, `deploy/profiles/*.yaml`):**

- Extend `emit.VIEW_KINDS` from `("base", "check", "seal", "relation", "witness", "outcome", "calc", "export")` to include **`"functional"`**, and return `"functional"` in `rules_split.views_by_kind` (1 per functional derivation, with any materialized candidate/witness view still counted under `"witness"` and any `conflict_policy = block` check view counted under `"outcome"`).
- Under `engine.view_budget` (default `MAX_VIEWS = 64`), count a deterministic projection functional view as weight **1** and a candidate-aggregating / precedence / rational functional view as weight **2**, so the partitioner accounts for heavier operator graphs instead of treating them as cheap set views.
- Under `engine.build_memory_mb` + `engine.view_cost_mb`, deploy profiles declare an explicit integer MB cost for `"functional"`, initialized conservatively to `view_cost_mb["calc"]` until empirically calibrated.

**Runner measurement:** actual Feldera compilation time, peak build memory, generated operator-crate count, and incremental step latency are measured by the GitHub Actions workflow **`.github/workflows/feldera-oracle.yml`** (job `compare`, `ubuntu-24.04`, orchestrated by `compiler/ci/run_feldera_oracle.sh` and `compiler/ci/feldera_shards.py`), across shards **`platform`** (`examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch[platform]` and `PLATFORM_TEST`), **`subsidy`** (`test_incremental_on_feldera_equals_batch[subsidy]`), and **`compiler-calc`** (`compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives`), plus a dedicated `compiler-functional` case once functional lowering lands. The `functional` weight is not lowered below `calc` until `compare` measurements on `examples/platform` confirm its actual build-memory cost.

### 3. "Or any relation depending on one" belongs to `calc_not_known_positive` in `partition_at_calc`, not `calc_aggregate`

In `compiler/rezono_compiler/rules.py`:

- **`calc_aggregate`** (inside `_check_rule`) only refuses an aggregate whose direct target atom has `role == "calc"`.
- **`calc_not_known_positive`** refuses both (a) any direct read of a `role == "calc"` relation that is negative or does not constrain `(state, reason) = ("known", "")` (inside `_check_rule`), and (b) any negation or aggregation over **any relation depending on a calculation** (`after = self.downstream(outputs)`), enforced in `Program.partition_at_calc`.

Both checks stay unchanged for `rezono 0` (`role == "calc"`). In `rezono 1`, per-derivation stratification replaces `partition_at_calc` for `functional` derivations (still refusing cycles through functional derivations, negation, or aggregation, and still refusing any dependency of `may_read` / `may_read_full` on a `functional` derivation or `calc` selection).

### 4. "Lifted across strata" requires closed-domain totalization, not an open calculation selection

In `compiler/rezono_compiler/rules.py` (`load`), every `role == "calc"` selection MUST have `world == "open"`, and `_worlds` propagates `open` to every derived relation reading it positively. Negating or aggregating over an open relation is unsound (except in `@absence`, which only describes what is recorded) because absence means unknown rather than false or empty.

Accordingly, lifting state tests (`is known`, `is unknown`, `is n/a`, `is invalid`) and aggregates across strata in `rezono 1` holds **only because a `functional` derivation is totalized over its declared finite domain `D`**:

- Every key in `D` has **exactly one row** `(key..., state, reason, value)` in the functional relation.
- The functional relation inherits `D`'s world: it is `closed` if and only if `D` is `closed` (a closed kind `K` for single-key derivations, or a closed base / lower-stratum `Bool` relation `D` for `over D(...)`). If `D` is `open`, the functional relation stays `open` and higher-stratum negation or aggregation over it remains refused outside `@absence` or a scoped completeness certificate.
- Reading `d(k) is unknown` / `is n/a` / `is invalid` / `is known` in a higher stratum is a **positive lookup** on the totalized state row (never negation-as-failure on a missing known value).
- Aggregating over a closed-domain functional derivation follows the four-state strictness rules of [`docs/rezono/expressions.md`](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) Appendix A.3: an `unknown` or `invalid` member propagates its state to `count`/`sum`/`min`/`max` rather than silently skipping the member or turning `unknown` into `0`.

Legacy `role == "calc"` inputs in `rezono 0` stay `world: open` with all existing refusals intact.

### 5. Cross-module readers of `core.dl` and the external-reader contract

Counting declarations inside `examples/platform/rules/core.dl` alone (30 -> 25) does not account for other modules in `examples/platform/rules/` that read relations declared in `core.dl`. Exact audit across all other `.dl` files in `examples/platform/rules/`:

| `core.dl` relation | `rezono 1` fate | Other `examples/platform/rules/*.dl` readers |
| --- | --- | --- |
| `provider` | Retired helper (`provides(s, f, _)`) | **1 file:** `other_provider.dl` |
| `zone_of` | Replaced by functional `Service.zone: Zone` | **4 files:** `cluster_placement.dl`, `in_zone_witness.dl`, `recovery_rule_delta.dl`, `tls_path.dl` |
| `runs` | Replaced by functional `Service.runs: Release` | **2 files:** `product_licence.dl`, `support_unknown.dl` |
| `flow` | Unchanged `Bool` relation | **7 files:** `choice_evidence.dl`, `cluster_flow.dl`, `firewall_witness.dl`, `in_zone_witness.dl`, `recovery_flow_delta.dl`, `recovery_rule_delta.dl`, `unique_evidence.dl` |
| `crossing`, `firewall_rule`, `recovery_reaches_out` | Unchanged `Bool` relations | **1–2 files:** `firewall_witness.dl`, `recovery_rule_delta.dl`, `recovery_flow_delta.dl` |

**External-reader contract whenever a relation is retired or replaced by a functional derivation:**

- **Same-pack rule modules** convert together as one pack in `rezono 1`:
  - Readers of a replaced functional property switch directly to the property (`zone_of(s, z)` -> `s.zone = z` in `cluster_placement.dl`, `in_zone_witness.dl`, `recovery_rule_delta.dl`, `tls_path.dl`; `runs(s, r)` -> `s.runs = r` and `runs(s, _)` -> `s.runs is known` in `product_licence.dl` and `support_unknown.dl`). Reading `s.zone = z` or `s.runs = r` requires `state = "known"`, preserving exact known-value semantics.
  - Readers of a retired helper either inline the underlying relation (`provider(available, function)` -> `provides(available, function, _)` in `other_provider.dl`) or, if a pack intentionally exposes a legacy name to external consumers, define a 1-line `Bool` projection in the owning module.
- **Cross-pack consumers (imported packs):** an imported pack MUST NOT silently remove a public relation read by downstream packs; it either retains a 1-line `Bool` compatibility projection or migrates all pinned consumers together with updated pack-hash pins.
- **Publication and test readers (channels, portals, oracles, acceptance tests):** every retired or reshaped relation is listed in the pack's intended-differences table (Section 7 for `core.dl`), naming the exact `rezono 1` derivation and state where readers find its content.

### 6. Fate of `rezono.calc/1` alongside `rezono.rules/2`

- **`rezono 0`:** `rezono.calc/1` (`contracts/calc.yaml`, `ir/calc.json`) stays supported unchanged for `rezono 0` packs and legacy `calc/*.yaml` files (`examples/subsidy`, `examples/subsidy-scheme`) throughout migration.
- **`rezono 1`:** all value-bearing derivations (single-subject calculations, versioned definitions, exceptions, decision tables, and multi-key functional derivations) lower to **`rezono.rules/2` (`role: functional`)**, never to `rezono.calc/1`. Rational functional views reuse the exact rational macros and Rust UDFs already proven in `calc_sql.py` and `udf/udf.rs`.
- **Retirement:** `rezono.calc/1` is retired only after every repository pack has migrated to `rezono 1` and its calculation values, states, and witnesses pass equivalence against DuckDB, Feldera, and the independent checker.

### 7. Reconciling `rezono 0` lowering with `decisions/language-calculations.md`

No claim is made that `rezono 0` lowers decision tables or arbitrary rule exceptions through `rezono.calc/1`. The exact `rezono 0` state is:

- [`decisions/language-calculations.md`](language-calculations.md) ("Refused") rejects `unless`, decision tables, state tests (`is known`, etc.), sets, and aggregates in `rezono.calc/1` with `R050`.
- [`decisions/language-exceptions.md`](language-exceptions.md) lowers ordered `unless` blocks on single-subject numeric/Boolean calculations into `rezono.calc/1` definitions with `overrides` (`compiler/rezono_compiler/rezono_exceptions.py`).
- [`decisions/language-tables.md`](language-tables.md) lowers decision tables through `compiler/rezono_compiler/rezono_table.py` into `rezono.rules/1` relations (`P`, `P_value`, `P_conflict`, etc.), not `rezono.calc/1`.

In `rezono 1`, all of these lower uniformly through `rezono.rules/2`.

### 8. Module format version is `rezono.module/5`

`contracts/rezono-module.yaml` already defines `rezono.module/1`, `/2`, `/3` (native `rezono 0` rules), and **`rezono.module/4`** (safe steps and `invariant intermediate within`, [`decisions/language-safe-steps.md`](language-safe-steps.md)).

Therefore **`rezono 1` uses `rezono.module/5`**:

- `rezono.module/1` through `rezono.module/4` keep their exact closed shapes and canonical bytes for `rezono 0` modules.
- `rezono.module/5` requires `module.rezono = "1"` (an omitted `rezono` line in a `rezono 1` pack is `R028`; mixed versions across one pack are `R027`), carries unified `derived` declarations (single-key inside `kind`/`extend`, multi-key at module scope with `params`, `over`, `unless`, `version`, `table`, `means`, `source`, `invariant` / `invariant intermediate within`, `explain`, `extend`, `total`), `step` declarations, and `example` blocks, and excludes `rezono 0`-only constructs (`rules` pipe blocks, `rule ... when ...`, `table priority`).
- `bundle/schema-bundle.json` records the pack's declared language version (`"0"` or `"1"`).

### 9. Actual standard packs only (no `std.units` or `std.money`)

`std.units` and `std.money` do not exist (and Rezono pack names are hyphenated lowercase, not dotted). The ten actual standard packs under `packs/` are:

`std-access`, `std-decision`, `std-explain`, `std-identity`, `std-loop`, `std-order`, `std-part`, `std-review`, `std-time`, and `std-view`.

For domain units and monetary quantities in `rezono 1`, packs use built-in scalar/quantity types (`Int`, `Text`, `Date`, `DateTime`, `Bool`, `Money<...>`, `Ratio`), `unit` declarations, and pattern-refined scalar aliases (`type ... pattern ...`), without citing nonexistent standard packs.

### 10. Exact `.dl` rule file census across the repository (including `build/`)

Counted directly from tracked `*.dl` files on `main`: **122 tracked `.dl` files in total**:

- **101 pack-owned `.dl` files** to convert once to `rezono 1`:
  - `examples/`: **53**
  - `packs/`: **29**
  - `run/`: **13**
  - `build/`: **6** (`build/rules/claim_release.dl`, `claims.dl`, `decision_rules.dl`, `policy_date.dl`, `selection.dl`, `tasks.dl`)
- **21 test-fixture `.dl` files** (kept as fixtures for legacy/oracle/conformance tests): `compiler/` (13), `tests/` (7), `edge/` (1).

All 101 pack-owned `.dl` files (including the 6 under `build/`) follow the single-conversion path directly to `rezono 1`.

## 6. Single-pass rule conversion and readiness gate

- Schemas, facts, parameters, and existing calculations continue migrating in `rezono 0` because their syntax carries forward unchanged into `rezono 1`.
- No pack `.dl` file or embedded `rules` (`|`) block is converted to `rezono 0` `rule ... when ...`. Existing rule files stay untouched as the live equivalence oracle until `rezono 1` lowering is ready, then convert once directly to `rezono 1` (standard packs first, then `build/`, `run/packs/`, and `examples/`).
- The `"Native conversion"` column in `compiler/tests/rezono/language_usage.py` (`scripts/language_usage.py`) MUST NOT report `"Ready"` for any pack containing rules until `rezono 1` derivation lowering is supported and tested; it also accounts for `build/` alongside `examples/`, `packs/`, and `run/`.

## 7. Per-derivation intended semantic differences for `examples/platform/rules/core.dl`

Whole-pack conversion equivalence tests ([migration equivalence](language-expression-semantics.md#4-migration-equivalence)) compare every derived result against the legacy `.dl` pack. For `examples/platform/rules/core.dl`, **every intended semantic difference is listed below**; the equivalence test asserts each listed difference explicitly by name and compares every other relation and known tuple for exact equality. **Any difference not listed here is a test error.**

| Legacy `core.dl` relation | `rezono 1` replacement | Intended semantic differences & where readers find retired content |
| --- | --- | --- |
| `provides(s, f, port)` | `derived provides(s: Service, f: Function, p: Int): Bool` | None (identical tuple set). |
| `provider(s, f)` | *Retired helper* | Retired. Readers use `provides(s, f, _)` (in particular `examples/platform/rules/other_provider.dl` reads `provides(available, function, _)`). |
| `asks(s, f)` | `derived asks(s: Service, f: Function): Bool` | None (identical tuple set). |
| `provider_chosen(s, f)` | `derived chosen(a: Service, f: Function): Service? over asks(a, f)` | Functional value over domain `asks(a, f)` carrying `known(b)` or `not_applicable` (`n/a`) instead of a `Bool` pair; choices for non-asked functions are outside the domain; **two conflicting `Choice` rows for the same `(a, f)` become `invalid multiple_values` with every candidate as witness** instead of silently producing duplicate `needs` rows. Readers needing the predicate test `not (chosen(a, f) is n/a)` (or `chosen(a, f) is known`). |
| `providers(f, n)` | *Retired helper* | Retired (replaced by `.one()` in `needs`). Readers needing the count compute `Service.where(provides(it, f, _)).count()`. |
| `needs(a, b, f)` | `derived needs(a: Service, f: Function): Service over asks(a, f)` | Reshaped from 3-column `Bool` relation `(a, b, f)` to 2-key functional derivation `(a, f) -> Service` with `(state, reason, value)` over `asks(a, f)`. Known rows match `needs(a, b, f)` whenever choices are unique. **Conflicting `Choice` rows or `> 1` unchosen providers yield `invalid multiple_values` with all candidate witnesses**; `0` providers with no choice yields `unknown no_value`. |
| `ambiguous_provider(a, f)` | *Retired finding* | Retired. Readers find its content at `needs(a, f)` with `state = "invalid"` (`needs(a, f) is invalid`, reason `multiple_values`, carrying all candidate providers as witness). Also catches conflicting `Choice` rows that `core.dl` silently allowed. |
| `unmet_need(a, f)` | *Retired finding* | Retired. Readers find its content at `needs(a, f)` with `state = "unknown"` (`needs(a, f) is unknown`, reason `no_value`). **Edge-case difference:** `core.dl` omitted `!provider_chosen(a, f)` in `unmet_need`, so a `Choice` pointing at a non-offering service previously emitted both `needs` and `unmet_need`; in `rezono 1`, `needs(a, f)` is `known` (the choice wins, so `needs(a, f) is unknown` is false) while `flow` still requires `provides(b, f, port)` and emits no flow. |
| `zone_of(s, z)` | `Service.zone: Zone` (domain `Service`) | Reshaped from binary `Bool` relation to single-key functional derivation `(s) -> Zone` with state. Known rows match `zone_of(s, z)` 1-for-1; a missing role/zone yields `unknown` instead of silent omission. External readers (`cluster_placement.dl`, `in_zone_witness.dl`, `recovery_rule_delta.dl`, `tls_path.dl`) read `s.zone`. |
| `on_cluster(s, c)` | `Service.cluster: ClusterClass` (domain `Service`) | Reshaped from binary `Bool` relation to single-key functional derivation `(s) -> ClusterClass` with state. Known rows match `on_cluster(s, c)` 1-for-1; missing role/cluster yields `unknown`. |
| `must_separate(a, b)` | `derived must_separate(a: Service, b: Service): Bool` | None on known inputs. |
| `flow(a, b, f, port)` | `derived flow(a: Service, b: Service, f: Function, port: Int): Bool` | Identical on unique-choice inputs; under conflicting `Choice` rows for `(a, f)`, `needs(a, f)` is `invalid`, so `flow` emits no tuple (previously emitted flows for both choices). |
| `crossing(a, b, za, zb, port)` | `derived crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int): Bool` | None (follows `flow` and `Service.zone`). |
| `firewall_rule(za, zb, port)` | `derived firewall_rule(za: Zone, zb: Zone, port: Int): Bool` | None. |
| `in_zone_policy(a, b, port)` | `derived in_zone_policy(a: Service, b: Service, port: Int): Bool` | None. |
| *New domain helper* | `derived needs_service(a: Service, b: Service): Bool` | Added helper naming the finite closed domain for `flow_from_step` (`Function.any(needs(a, it) = b)`). |
| `flow_from_step(a, b, n)` | `derived flow_from_step(a: Service, b: Service): Int over needs_service(a, b)` | Reshaped from 3-column `Bool` relation `(a, b, n)` to 2-key functional derivation `(a, b) -> Int` over `needs_service(a, b)`. Known rows match 1-for-1; a missing `step` yields `unknown` instead of silent omission. |
| `stable_release(r, p, d)` | *Retired helper* | Retired (inlined as `Release.where(product = p and stable = yes)`). Readers read `Release` facts directly. |
| `has_stable(p)` | *Retired helper* | Retired (inlined into `Product.newest_day`). Readers test `p.newest_day is known` (or `not (p.newest_day is n/a)`). |
| `newest_day(p, d)` | `Product.newest_day: Int` (domain `Product`) | Reshaped from binary `Bool` relation to single-key functional derivation `(p) -> Int` with state. Known rows match 1-for-1; a product with no stable release gets `not_applicable empty` instead of no row. |
| `pinned(s)` | `Service.pin: Release?` (domain `Service`) | Reshaped from unary `Bool` relation to single-key functional derivation `(s) -> Release?` (`known(r)` or `n/a`). **Two conflicting `Pin` rows for one service become `invalid multiple_values` with all competing pins as witness** instead of silently producing multiple `runs` rows. Readers needing `pinned(s)` test `not (s.pin is n/a)` (or `s.pin is known`). |
| `runs(s, r)` | `Service.runs: Release` (domain `Service`) | Reshaped from binary `Bool` relation to single-key functional derivation `(s) -> Release`. Known rows match 1-for-1 when pins and newest-day stable releases are unique. **Conflicting `Pin` rows or two tied stable releases on `newest_day` become `invalid multiple_values` with all candidate witnesses**; missing stable release (when unpinned) becomes `unknown no_value` (or propagates `n/a`/`unknown` from `newest_day`). External readers (`product_licence.dl`, `support_unknown.dl`) read `s.runs` (and `s.runs is known`). |
| `behind_newest(s, r)` | `Service.behind_newest: Bool` (key `(s: Service)`) | **Shorter key `(s)` instead of `(s, r)`** because `s.runs` is functional (every service has at most one known release). Readers needing the release `r` join `Service.behind_newest` with `Service.runs`. |
| `outside_reaches_inside(a, b)` | `derived outside_reaches_inside(a: Service, b: Service): Bool` | None. |
| `recovery_reached(a, b)` | `derived recovery_reached(a: Service, b: Service): Bool` | None. |
| `recovery_reaches_out(a, b, f)` | `derived recovery_reaches_out(a: Service, b: Service, f: Function): Bool` | None. |
| `authenticates(s)` | `Service.authenticates: Bool` | None. |
| `unauthenticated_target(b, f)` | `derived unauthenticated_target(target: Service, fn: Function): Bool` | None. |
| `verified(s)` | `Service.verified: Bool` | None. |
| `unverified_supply(s)` | `Service.unverified_supply: Bool` | None. |
| `build_reaches_tenant(a, b)` | `derived build_reaches_tenant(a: Service, b: Service): Bool` | None. |

## 8. Ordered rollout

1. **Feldera calculation parity:** compare all current `rezono.calc/1` states, reasons, and witness steps on Feldera against DuckDB and the independent checker across the examples before emitting `rezono 1` functional views on Feldera.
2. **Version switch:** reader and compiler dispatch by declared `rezono` version (`0` and `1` side by side), `rezono.module/5` contract, `R027`/`R028` version checks, `table priority` refusal with `table first` hint in `rezono 1`, and pack language version in `bundle/schema-bundle.json`.
3. **Functional derivation IR, checker, and engines (`rezono.rules/2`):** `role: functional` with closed `domain`, co-located `(state, reason, value)`, `conflict_policy`, per-derivation stratification (keeping `may_read` / `may_read_full` strictly in the `Bool` layer), multi-candidate conflict witnesses, independent checker verification, `"functional"` view kind and profile weight in `emit.py`/`rules_split.py`, one co-located view per functional derivation on DuckDB and Feldera, Soufflé test oracle lowering for the non-rational fragment, and runner cost measurement in `.github/workflows/feldera-oracle.yml`.
4. **`rezono 1` syntax and small tooling:** unified `derived` (single-key properties, multi-key declarations, `over`, `.one()`, method-form `.where(...)` / `.count(pred)` / relation-as-tuple-set, `means` + `@`), `example` blocks with `W109`, two-knowledge-date comparison, period shorthand, digit grouping underscores, Ohm-derived syntax-highlighting grammar, and `rezono fmt`.
5. **Single-pass pack rule conversion:** convert all 101 pack-owned `.dl` files once (standard packs first, then `build/`, `run/packs/`, and `examples/`, converting platform safe steps alongside platform rules), gating `scripts/language_usage.py`'s `"Native conversion"` column on `rezono 1` derivation lowering and enforcing whole-pack equivalence with explicit intended-difference tables.

## Considered

- **Converting all 101 pack-owned `.dl` files twice (first to `rezono 0` `rule ... when ...`, then to `rezono 1`).** Rejected: doubles the largest migration and parity-testing effort in the repository for a workbench syntax that will not be part of the first public release.
- **Lowering `rezono 1` functional derivations by naive table-style Datalog desugaring into `rezono.rules/1`.** Rejected: multiplies views by 6–11× per value, inflating pipeline counts, cross-pipeline exports, and Feldera build memory, and cannot represent multi-key derived domains or published multi-candidate conflict findings cleanly.
- **Keeping `table priority` in `rezono 1`.** Rejected: implicit tie-breaking from enum declaration order makes schema ordering silently alter rule outcomes; `table first` makes precedence explicit in the table itself.
- **Allowing `may_read` / `may_read_full` to depend on functional derivations.** Rejected: keeps `checker/rezono_checker/access.py` small and avoids circularity between reading a value's state/reason and deciding whether a role may read that value.
