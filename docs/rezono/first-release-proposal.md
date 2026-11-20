# First-release language proposal: unified derivations (`rezono 1`)

> **Status: Proposal only — not a specification or a design decision.**
> Nothing in this document is built or scheduled; no pack is converted, no existing rule file is edited, and no red test is attached. Work on `rezono 0` continues unchanged. This trial examines how `rezono 1` would look as the first released version of Rezono with a single derivation form, so the owner can choose between the paths in [Section 13](#13-two-paths-and-recommendation).

---

## Part A: One derivation form

### 1. The proposal

Today Rezono has two separate derivation mechanisms: `rule` lowers to a Datalog set relation (multiple keys, stratified recursion and aggregation, no value columns or value states), while `derived` lowers to a single-subject calculation (`rezono.calc/1`, carrying value states, reasons, exceptions, versions and decision tables, but refusing sets, multi-key indexing and recursion). This split forces domain authors to choose an execution mechanism before expressing a domain concept, and splits one thought across multiple rules (for instance, `needs`, `ambiguous_provider` and `unmet_need` in `examples/platform/rules/core.dl`).

In `rezono 1`, every derivation is written with **one `derived` form**:

- **Key:** one or more typed elements. A single-key derivation on a kind `K` is written as a derived property inside `kind K` or `extend K` (or `extend s: K` when naming the subject binder). A multi-key derivation is written at module scope with explicit typed key parameters, e.g. `derived needs(a: Service, f: Function): Service`.
- **Value with state:**
  - **`Bool` stays a set / relation.** Each succeeding derivation is a proof of membership, multiple independent proofs are preserved, and stratified positive recursion is allowed. A `Bool` derivation carries no extra state columns.
  - **`T*` is a set-valued derivation.** It yields all derived members for a key (with no uniqueness conflict and recursion permitted just as for `Bool`).
  - **A single value `T` (or optional `T?`) is functional with a state.** For every key in its domain:
    - exactly one distinct value gives `known(v)` with its witness;
    - two or more distinct values give `invalid` with a reason code and **every candidate value and its proof as a witness** — Rezono never silently picks one;
    - no value gives `unknown` with a reason code (or `n/a` when the result is optional `T?` or an explicit guard is inapplicable).
- **Uniform modifiers.** Ordered and sibling `unless` blocks, `version` blocks (`valid`, `known`, `replaces`), `table` blocks (`unique`, `first`, `collect`), and `@` source citations work on **every** derivation — single-key or multi-key, `Bool` or single-valued — reusing existing core reason codes wherever they apply (`exception_conflict`, `versions_overlap`, `no_row_applies`, `no_value`, plus `multiple_values` when `.one()` or competing clauses yield two distinct values without a sibling `unless` block).
- **Converting a set to a functional value (`.one()`).** `S.one()` turns a closed set `S: T*` into a functional value: `|S| = 1` gives `known(v)` (witnessed by the single member and `count = 1`); `|S| = 0` gives `unknown no_value` (or `n/a` when the declared type is `T?`); `|S| > 1` gives `invalid multiple_values` carrying every member of `S` as a conflict witness.

Two illustrative derivations (one multi-key functional, one recursive `Bool`):

```rezono
derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = Service.where(provides(it, f, _)).one()
  unless not (chosen(a, f) is n/a) then chosen(a, f)

derived within(part: Constituent, whole: Constituent): Bool
  = part.part_of = whole or within(part.part_of, whole)
```

#### Readability improvements included in this trial

Two open readability candidates are worked out directly in this unified form (while keeping all seven punctuation symbols `?`, `*`, `+`, `..<`, `@`, `-`, `_` strictly as symbols with no keyword synonyms):

1. **Derived property where a subject exists.** Any derivation whose key is one element of a kind `K` belongs inside `kind K` or `extend K` (e.g. `Service.zone: Zone`, `Service.runs: Release`, `Service.authenticates: Bool`, `Product.newest_day: Int`). The boundary is simple and objective: **one kind key** -> derived property on that kind; **two or more keys** -> module-level `derived name(k1: T1, k2: T2, ...): R`. No artificial wrapper kind is ever invented for n-ary relations. Where a pack declares `inverse` slots ([`decisions/language-inverse-references.md`](../../decisions/language-inverse-references.md)), properties read even more concisely (`product.offers`); where no inverse is declared, `.where(...)` over the target kind works without modifying the schema.
2. **Simpler counting and summing within the method form.** Today a filtered rule aggregate requires positional wildcards, outer parentheses and `it.` prefixes: `(edge(_, _) where it.pred = x).count()` and `ledger_line(a, _, _).sum(it.cents)`. Staying strictly inside the method form ([`v0.md`](v0.md#2-settled-choices), no second `count ... where ...` form):
   - add postfix `.where(predicate)` at the same precedence as `.count()`, `.sum(expr)`, `.min(expr)`, `.max(expr)`, `.any(predicate)`, `.all(predicate)`, `.none(predicate)` and `.one()`;
   - allow an optional filter predicate directly in `.count(predicate)` (shorthand for `.where(predicate).count()`);
   - let a relation name stand for its tuple set whose declared column names are in scope inside `.where(...)` and aggregates, omitting `it.` whenever unambiguous (retaining `R011` on element/outer collisions, where `it.name` or an explicit outer binder such as `extend s: Service` disambiguates).
   - Thus `(edge(_, _) where it.pred = x).count()` becomes `edge.count(pred = x)` (or `edge.where(pred = x).count()`), and `ledger_line(a, _, _).sum(it.cents)` becomes `ledger_line.where(application = a).sum(cents)`.

---

### 2. Fixed invariants and constraints

- **No built-in `best` or `first` over sets; termination stays guaranteed.** Every program still terminates: no unbounded recursion, no arithmetic inside recursion, and no `min` or `max` inside recursion for now. A built-in `best` or `first` operator over sets remains rejected because it conceals the candidate inventory, exclusions and tie-breaking policy. (Static row-order `table first` remains explicit in the authored text.)
- **Symbols remain symbols.** `?`, `*`, `+`, `..<`, `@`, `-` and `_` stay symbols with no word synonyms introduced beside them.
- **New language version (`rezono 1`) preserving `rezono 0` ([`v0.md`](v0.md#4b-language-version-and-deprecation) §4b).** Every pack declaring `rezono 0` keeps its exact syntax, semantics and canonical printed form; a pack moves to `rezono 1` only by changing its header line. **What the reader and compiler still lack to read a second version:**
  1. `rezono/src/module-header.ts` already parses `rezono <n>` as a string, but neither `rezono/src/` nor `compiler/rezono_compiler/` dispatches grammar rules, type rules, diagnostics or lowering by declared version.
  2. `compiler/rezono_compiler/rezono_module.py` (`header_errors`) hardcodes `module.get("rezono") != "0"` and rejects every other version.
  3. There is no pack-wide check that all modules of a pack declare the same version (`R027`), nor an error for an omitted `rezono` line in `rezono 1` (`R028`, versus warning `W106` in `rezono 0`).
  4. `contracts/rezono-module.yaml` and `bundle/schema-bundle.json` do not yet record the pack's language version or gate a version-specific module form (`rezono.module/4`).
  5. Phased deprecation (`W107` -> `R028`) and promoting rights-above-clearance from warning (`W102` in `rezono 0`) to error (in `rezono 1`) are not yet wired to a version switch.
- **Addressing the two objections in [`decisions/language-native-rules.md`](../../decisions/language-native-rules.md).**
  1. *Artificial subjects and hidden multiple proofs:* Multi-key derivations remain module-level declarations with explicit typed keys (no wrapper kinds), and `Bool` (and `T*`) derivations remain ordinary sets where every succeeding derivation keeps its own independent witness.
  2. *Changing arity and proofs by adding state rows to every relation:* `Bool` derivations remain plain sets of keys — their arity, witnesses and proofs do not change. Only non-`Bool` single-valued derivations carry a `(state, reason, value)` payload, and only over their declared domain.
- **What happens to the four refusals separating rules and calculations today:**
  1. **`calc_not_known_positive`** (`compiler/rezono_compiler/rules.py`): Currently a rule may read a calculation only positively with `state = "known"` and `reason = ""`, which forbids `is known` / `is n/a` / `is unknown` / `is invalid` inside a derivation. **In `rezono 1`, lifted across strata:** once a functional derivation's state is computed in a strictly lower stratum over a closed domain, a higher-stratum derivation may read its value (`d(k) = v`, requiring `state = "known"`) or test its state positively (`d(k) is known`, `is unknown`, `is n/a`, `is invalid`), with the checker verifying the state row and its witness. Note that because `is` always yields `true` or `false` ([`v0.md`](v0.md#7b-truth-and-value-states) §7b), guarding an `unless` with `chosen(a, f) is known` alone would silently fall back to the base when `chosen(a, f)` is `invalid`; writing `unless not (chosen(a, f) is n/a) then chosen(a, f)` preserves both `known` and `invalid` without masking a conflict.
  2. **`calc_aggregate`** (`compiler/rezono_compiler/rules.py`): Currently aggregating over a calculation or any relation depending on one is refused. **In `rezono 1`, lifted across strata** over closed domains, following the four-state strictness rules of [`expressions.md`](expressions.md#appendix-a-truth-tables-normative) Appendix A.3 (an `unknown` or `invalid` member propagates its state to `count`/`sum`/`min`/`max` rather than dropping the member or turning `unknown` into `0`).
  3. **`rule_calc_cycle`** (`compiler/rezono_compiler/rules.py`, `partition_at_calc`): Currently the whole program is cut into one pre-calc phase, one calc phase and one post-calc phase. **In `rezono 1`, replaced by per-derivation stratification:** a true cycle through any functional derivation, negation or aggregate remains refused (`R009` / `not_stratified`), while acyclic interleaving (`Bool` recursion -> functional derivation A -> `Bool` derivation B -> functional derivation C) is permitted.
  4. **Read access depending on a calculation** (`may_read cannot depend on a calculation selection`, in `compiler/rezono_compiler/pack.py` and `checker/rezono_checker/rules.py`): **Remains refused.** `may_read` and `may_read_full` stay strictly in the `Bool` relational layer so `checker/rezono_checker/access.py` keeps its small independent trust boundary and never faces circularity between reading a value's state/reason and deciding whether a role may read that value.
- **What a conflict does at publication time (blocking invariant vs published finding).** Today `P_conflict` on a `table unique` is a blocking `@invariant`, whereas `ambiguous_provider` in `examples/platform/rules/core.dl` is a published finding so operators can inspect the ambiguity and add a `Choice`. In `rezono 1`, **deriving the `invalid` state is separated from blocking publication**:
  - **Rule-structure contradictions always block publication** (automatic invariant): unresolved `versions_overlap`, sibling `unless` clashes (`exception_conflict`), and overlapping `table unique` rows mean the rules themselves contradict each other.
  - **Data-multiplicity conflicts from `.one()` (`invalid multiple_values`) publish as findings by default** on `partial` derivations (the default per [`v0.md`](v0.md#5d-effect-classes-and-totality) §5d): the functional derivation records `(key..., "invalid", "multiple_values")` with every candidate as witness, downstream `Bool` derivations reading its value emit no false positive tuple, and diagnostic views can surface `needs(a, f) is invalid` directly — replacing `ambiguous_provider` without aborting publication. A pack that wants data conflicts to block publication writes `check` / `require` (e.g. `check unique_provider: not (needs(a, f) is invalid)`) or marks the derivation `total`.
- **Five rules for Feldera (the target engine):**
  1. **State after recursion, never inside:** Value states, uniqueness checks and conflict aggregation are always computed after any recursive fixed point, never inside a `DECLARE RECURSIVE VIEW`.
  2. **Every multi-key functional derivation names its domain, and a product of kinds is not a domain:** Single-key derivations on `extend K` use the closed kind `K`; multi-key functional derivations must name a finite, closed domain relation (`over D(k1, ..., kn)`). A Cartesian product of kinds (e.g. `Service × Function`) is rejected at compile time because materializing `unknown` rows for every pair explodes incremental state.
  3. **`Bool` stays an ordinary set:** A `Bool` derivation compiles to a plain set view with no extra state or conflict views, so only non-`Bool` functional derivations pay for state views.
  4. **Co-locate state in the same view as the value where possible:** Emit one view `(key..., state, reason, value)` per functional derivation rather than splitting `P`, `P_value`, `P_conflict`, `P_applies` and helpers into 6–11 views.
  5. **Verify current calculation states and witnesses on Feldera first:** Today `examples/test_feldera_rules.py` checks rule views and known calculation selections, not full calculation states, reasons and witness steps across real packs (the publisher computes with DuckDB). Comparing all current calculation states and witnesses on Feldera against DuckDB and the checker is a prerequisite before adding the unified form to Feldera.

---

### 3. The platform trial: `examples/platform/rules/core.dl`

Below is the complete rewrite of `examples/platform/rules/core.dl` in the proposed `rezono 1` form (for inspection only — the pack itself is unchanged). It uses the existing schema of `examples/platform/schema/core.yaml` verbatim, without adding inverse slots.

```rezono
rezono 1
pack platform

-- What a service offers and asks follows from its product.
derived provides(s: Service, f: Function, p: Int): Bool
  = Offer.any(product = s.product and function = f and port = p)

derived asks(s: Service, f: Function): Bool
  = Demand.any(product = s.product and function = f)

-- Who serves a need: a written choice wins; else the only provider.
derived chosen(a: Service, f: Function): Service?
  over asks(a, f)
  = Choice.where(service = a and function = f).provider.one()

derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = Service.where(provides(it, f, _)).one()
  unless not (chosen(a, f) is n/a) then chosen(a, f)

-- Zone, cluster class, version and supply checks per service or product.
extend p: Product
  derived newest_day: Int
    = Release.where(product = p and stable = yes).max(released_on_day)

extend s: Service
  derived zone: Zone = role.zone
  derived cluster: ClusterClass = role.cluster_class

  derived pin: Release?
    = Pin.where(service = s).release.one()

  derived runs: Release
    = Release.where(it.product = s.product and stable = yes and released_on_day = s.product.newest_day).one()
    unless not (pin is n/a) then pin

  derived behind_newest: Bool
    = runs.released_on_day < product.newest_day

  derived authenticates: Bool
    = asks(s, identity) or provides(s, identity, _)

  derived verified: Bool
    = Artifact.any(for_service = s and built_by.role.build_authority = yes and signed = yes)

  derived unverified_supply: Bool
    = role.runs_images = yes and not verified

-- Flows, firewall rules, network policies and step ordering.
derived must_separate(a: Service, b: Service): Bool
  = a.cluster != b.cluster

derived flow(a: Service, b: Service, f: Function, port: Int): Bool
  = needs(a, f) = b and provides(b, f, port)

derived crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int): Bool
  = flow(src, dst, _, port) and src.zone = za and dst.zone = zb and za != zb

derived firewall_rule(za: Zone, zb: Zone, port: Int): Bool
  = crossing(_, _, za, zb, port)

derived in_zone_policy(a: Service, b: Service, port: Int): Bool
  = flow(a, b, _, port) and a.zone = b.zone

derived needs_service(a: Service, b: Service): Bool
  = Function.any(needs(a, it) = b)

derived flow_from_step(a: Service, b: Service): Int
  over needs_service(a, b)
  = max(a.step, b.step)

-- Security and boundary findings.
derived outside_reaches_inside(a: Service, b: Service): Bool
  = crossing(a, b, za, zb, _) and za.outside = yes and zb.entry_boundary = no

derived recovery_reached(a: Service, b: Service): Bool
  = crossing(a, b, _, zb, _) and zb.isolated_recovery = yes

derived recovery_reaches_out(a: Service, b: Service, f: Function): Bool
  = flow(a, b, f, _) and a.zone.isolated_recovery = yes and b.zone.isolated_recovery = no
    and f.recovery_allowed = no

derived unauthenticated_target(target: Service, fn: Function): Bool
  = crossing.where(dst = target).any(provides(target, fn, port))
    and fn.open_by_design = no and not target.authenticates

derived build_reaches_tenant(a: Service, b: Service): Bool
  = flow(a, b, _, _) and a.role.build_authority = yes and b.zone.workload = yes
```

#### Derivation inventory, domains and retired rules

| # | New derivation | Key | Value | Domain | Current `core.dl` rules replaced or retired |
|---:|---|---|---|---|---|
| 1 | `provides` | `(s: Service, f: Function, p: Int)` | `Bool` | Set | Replaces `provides`; retires `provider` |
| 2 | `asks` | `(s: Service, f: Function)` | `Bool` | Set | Replaces `asks` |
| 3 | `chosen` | `(a: Service, f: Function)` | `Service?` | `asks(a, f)` | Replaces `provider_chosen` (and detects duplicate `Choice` conflicts) |
| 4 | `needs` | `(a: Service, f: Function)` | `Service` | `asks(a, f)` | Replaces `needs` (2 clauses); retires `providers`, `ambiguous_provider` (`needs is invalid`), `unmet_need` (`needs is unknown`) |
| 5 | `Product.newest_day` | `(p: Product)` | `Int` | `Product` | Replaces `newest_day`; retires `stable_release`, `has_stable` |
| 6 | `Service.zone` | `(s: Service)` | `Zone` | `Service` | Replaces `zone_of` |
| 7 | `Service.cluster` | `(s: Service)` | `ClusterClass` | `Service` | Replaces `on_cluster` |
| 8 | `Service.pin` | `(s: Service)` | `Release?` | `Service` | Replaces `pinned` (and detects duplicate `Pin` conflicts) |
| 9 | `Service.runs` | `(s: Service)` | `Release` | `Service` | Replaces `runs` (2 clauses; also catches tied newest-day releases and missing stable releases) |
| 10 | `Service.behind_newest` | `(s: Service)` | `Bool` | Set | Replaces `behind_newest` (`r` is uniquely `s.runs`) |
| 11 | `Service.authenticates` | `(s: Service)` | `Bool` | Set | Replaces `authenticates` (2 clauses) |
| 12 | `Service.verified` | `(s: Service)` | `Bool` | Set | Replaces `verified` |
| 13 | `Service.unverified_supply` | `(s: Service)` | `Bool` | Set | Replaces `unverified_supply` |
| 14 | `must_separate` | `(a: Service, b: Service)` | `Bool` | Set | Replaces `must_separate` |
| 15 | `flow` | `(a: Service, b: Service, f: Function, port: Int)` | `Bool` | Set | Replaces `flow` |
| 16 | `crossing` | `(src: Service, dst: Service, za: Zone, zb: Zone, port: Int)` | `Bool` | Set | Replaces `crossing` |
| 17 | `firewall_rule` | `(za: Zone, zb: Zone, port: Int)` | `Bool` | Set | Replaces `firewall_rule` |
| 18 | `in_zone_policy` | `(a: Service, b: Service, port: Int)` | `Bool` | Set | Replaces `in_zone_policy` |
| 19 | `needs_service` | `(a: Service, b: Service)` | `Bool` | Set | Explicit named domain for `flow_from_step` (Feldera rule 2) |
| 20 | `flow_from_step` | `(a: Service, b: Service)` | `Int` | `needs_service(a, b)` | Replaces `flow_from_step` (2 clauses) |
| 21 | `outside_reaches_inside` | `(a: Service, b: Service)` | `Bool` | Set | Replaces `outside_reaches_inside` |
| 22 | `recovery_reached` | `(a: Service, b: Service)` | `Bool` | Set | Replaces `recovery_reached` |
| 23 | `recovery_reaches_out` | `(a: Service, b: Service, f: Function)` | `Bool` | Set | Replaces `recovery_reaches_out` |
| 24 | `unauthenticated_target` | `(target: Service, fn: Function)` | `Bool` | Set | Replaces `unauthenticated_target` |
| 25 | `build_reaches_tenant` | `(a: Service, b: Service)` | `Bool` | Set | Replaces `build_reaches_tenant` |

#### Before and after rule counts

| Metric | Current `core.dl` | Proposed `rezono 1` | Change |
|---|---:|---:|---:|
| Declarations / derivations | 30 `.decl` relations | 25 `derived` declarations (17 `Bool`, 8 functional) | −5 (−17%) |
| Rule clauses / definitions | 34 Datalog clauses | 25 single-definition bodies | −9 (−26%) |
| Retired helper / finding relations | — | 6 retired (`provider`, `providers`, `ambiguous_provider`, `unmet_need`, `stable_release`, `has_stable`); +1 domain helper (`needs_service`) | Net −5 |

Two semantic observations surfaced by the trial:

1. **Stricter bug detection for free:** In `core.dl`, two conflicting `Choice` rows for `(a, f)`, two `Pin` rows for one `Service`, or two stable releases on the same `newest_day` silently emit multiple `needs` or `runs` rows. In `rezono 1`, `.one()` turns all three into explicit `invalid multiple_values` states with every competing row as witness.
2. **Edge case in `unmet_need`:** `core.dl` line 22 defines `unmet_need(a, f) :- asks(a, f), providers(f, n), n = 0` without `!provider_chosen(a, f)`. In `rezono 1`, if a `Choice` points at a service that does not offer `f`, `needs(a, f)` is `known` (the choice wins) while `flow` still checks `provides(b, f, port)`. If another module in `examples/platform` (such as `other_provider.dl`) needs the legacy names `provider`, `ambiguous_provider` or `unmet_need`, each is a one-line `Bool` projection (`needs(a, f) is invalid`, `needs(a, f) is unknown`) rather than duplicated logic.

---

### 4. Underlying form, checker and engine view analysis

#### Starting point: `outcome` and table lowering

Two existing pieces already model a functional value with a state for a single subject kind:

- **`outcome` in `rezono.rules/1` ([`contracts/rules.yaml`](../../contracts/rules.yaml)):** A derived relation with 3 key columns `(element, state, reason)` over a 1-column base kind. `rules_sql.py` adds 2 check views (`<name>__total`, `<name>__state`), and `checker/rezono_checker/check.py` verifies `outcome_total` and `outcome_state` (each element has one state: `known` with `""`, or `unknown`/`not_applicable` with one or more reasons).
- **Decision-table lowering (`compiler/rezono_compiler/rezono_table.py`, [`docs/rezono/publication.md`](publication.md#91-a-decision-table-under-unique) §9.1):** Lowers a 1-key enum table to Datalog rules emitting `P` (`@outcome`), `P_value`, `P_conflict` (`@invariant` for `unique`), `P_row`, `P_cell`, `P_applies`, and (when testing required slots) `P_has`, `P_missing`, `P_false`, `P_open`, `P_undecided` — **6 to 11 derived relations per value**, before counting outcome checks and witnesses.
- **Calculation SQL (`compiler/rezono_compiler/calc_sql.py`):** Co-locates value, state and reason `(subject, state, n, d, b, reason, definition, version)` in **one view per calculation rule** for a single subject kind, using DuckDB 128-bit macros and Feldera Rust UDFs (`udf/udf.rs`).

#### Does existing Rule IR + `rezono.calc/1` suffice?

**No — pure desugaring to `rezono.rules/1` and `rezono.calc/1` does not suffice**, for four concrete reasons:

1. **`outcome` is restricted to one base kind and three states:** `checker/rezono_checker/rules.py` requires `outcome` to target a 1-column base kind and accepts only `known`, `unknown` and `not_applicable` — not a multi-key derived domain like `asks(a, f)` or `needs_service(a, b)`, and not a published `invalid` finding state.
2. **Datalog view explosion breaks Feldera's budget:** Lowering each functional derivation the way `rezono_table.py` lowers a table (6–11 relations + 2 outcome checks) blows past Feldera's 64-view pipeline budget (`emit.MAX_VIEWS = 64`) on a single module (quantified below).
3. **`rezono.calc/1` is single-subject, single-phase and numeric/Boolean-only:** It fixes one `subject` kind per program, runs in a single phase between pre-calc and post-calc rules (`partition_at_calc`), and cannot represent multi-key functional derivations, kind/enum outputs, or set aggregates.
4. **Multi-candidate conflict witnesses:** A functional conflict must carry *every* candidate value and its proof, not only a pair of conflicting row numbers.

#### Required extensions (IR, witnesses, checker and engines)

- **`contracts/rules.yaml` (additive `functional` relation role, e.g. `rezono.rules/2`):**
  - Keep `derived` unchanged for `Bool` (and `T*`) sets.
  - Add a `functional` derived relation carrying: `key` (1+ typed columns), `domain` (mandatory name of a closed base or lower-stratum derived relation matching `key`, enforcing Feldera rule 2 in the IR), `value` (one typed column: `string` for refs/enums/text, `integer`, `rational`, or `boolean`) with co-located `state` and `reason`, `conflict_policy` (`block` for rule-structure conflicts vs `publish` for `.one()` multiplicity conflicts), and ordered precedence/version/candidate rules strictly in a higher stratum than `domain` and outside recursion (enforcing Feldera rule 1).
  - Replace the single-cut `partition_at_calc` with per-derivation stratification (still rejecting cycles through functional derivations, negation or aggregation, and still rejecting any `may_read` / `may_read_full` dependency on a functional derivation).
- **Witnesses (`contracts/proof.yaml`):**
  - `known(v)`: winning clause/version/candidate plus absent higher-precedence guards; for `.one()`, the single candidate plus the candidate-group digest (`count = 1`, `contributors_sha256`, reusing the existing aggregate witness shape).
  - `unknown(reason)` / `not_applicable`: domain key plus the cause (empty candidate group `count = 0`, absent version, or upstream non-known state row).
  - `invalid(reason)`: all competing candidates (group digest + candidate rows, resolved on demand from the candidate query or from one candidate view when materialized).
- **Checker (`checker/rezono_checker/`):**
  - Generalize `outcome_total` and `outcome_state` from 1-column base kinds to any declared `domain` relation (including multi-key derived domains), verify `state` against the candidate set (`count = 0` -> `unknown`/`n/a`, `count = 1` -> `known` matching the unique value, `count > 1` -> `invalid` with all distinct candidates matching the conflict witness), and reject publication when `conflict_policy = block` has any `invalid` row.
  - Keep `checker/rezono_checker/access.py` unchanged in trust boundary: verify that `may_read` and `may_read_full` depend only on `Bool` / base relations.
- **Three engines:**
  - **DuckDB (batch & publisher):** Emit one `CREATE OR REPLACE TABLE` per functional derivation: `LEFT JOIN` `domain` with a `GROUP BY key` over the candidate query (`COUNT(DISTINCT val)`, `MIN(val)` when `count = 1`, `CASE` producing `(key..., state, reason, value)`). Exact rationals keep using `DUCKDB_MACROS` (`HUGEINT`).
  - **Soufflé (independent oracle):** Inside `compiler/tests/souffle.py` only, lower the non-rational fragment of each functional derivation to standard Datalog relations (candidate relation + `count` + `(key, state, reason, value)` projection) and compare projected tuples against DuckDB and Feldera. Soufflé stays an independent oracle without forcing Datalog view proliferation onto Feldera.
  - **Feldera (incremental target engine):** Emit **one `CREATE MATERIALIZED VIEW`** per functional derivation (`LEFT JOIN` over the closed `domain` with `GROUP BY key` on candidates, strictly outside `DECLARE RECURSIVE VIEW`, honoring Feldera rules 1–4). Deterministic single-valued path projections (`Service.zone`, `Service.cluster`) need only a `LEFT JOIN` with zero candidate views. Only `conflict_policy = block` adds one tiny invariant view (`WHERE state = 'invalid'`). First verify all current calculation states, reasons and witness steps on Feldera against DuckDB and the checker (Feldera rule 5).

#### Exact view count for module `core` (measured vs estimated)

Compiling `examples/platform` with `python -m rezono_compiler compile examples/platform <out>` produces `ir/rules.json` (265 derived relations, 393 rules across the whole pack) and `engine/pipelines.json` (8 rule pipelines plus `integrity`). Counting module `core` exactly as the pipeline budget counts (`rules_split.views_by_kind`: derived relations + materialized witness views + outcome/bound checks):

| View category (module `core`) | Current `core.dl` (measured) | `rezono 1` — naive table-style Datalog desugaring | `rezono 1` — co-located functional views (proposed) |
|---|---:|---:|---:|
| `Bool` derived relation views | 30 | 17 | 17 |
| Functional derived views | 0 | 48–88 (8 × 6–11 relations) | 8 (1 combined view each) |
| Materialized witness / candidate views | 3 (`flow`, `newest_day`, `providers`) | ~2–10 | 2 (`flow`, `needs_service`) to 6 (if 4 `.one()` candidate views are materialized) |
| Outcome / conflict check views | 0 | 16 (8 × 2 outcome checks) | 0 (published conflicts) to 2 (if `chosen`/`pin` block) |
| **Total budget views for `core`** | **33** | **~83–131** | **27–33** |

Co-locating `(key..., state, reason, value)` in one view keeps module `core` at **27–33 views** (at or below today's 33), whereas naive Datalog desugaring explodes to **83–131 views** — more than double Feldera's 64-view pipeline budget on one module alone.

---

## Part B: The language of the first release

### 5. Scope of `v0.md` constructs

**Verdict: keep the core declarative surface in the first release; defer seven advanced constructs to later and drop `priority` tables.** The first release (`rezono 1`) includes schemas (`kind`, `extend`, `enum`, `unit`, `world open/closed`, `inverse`, refinements), facts (`fact`, `decide`, `assume`, dated facts), versioned `param`s, unified `derived` (single values, `Bool` sets, `T*` sets, `unless`, `version` on the date and knowledge axes with `replaces`, `table` under `unique`/`first`/`collect`), `check`/`warn`/`require`, `reason`, `rounding`, `example`, `ask`/`suppose`/`propose`, and `@` source citations. For the eight defer/drop candidates:

- **Phases and setups as version axes (`during`, `in`):** **Later** — calendar validity (`valid`) and knowledge cut (`known`) cover regulatory and platform versioning now, while `during` needs generic `std.Order` views and `in` overlaps with sweep variants.
- **Generic theories and views (`theory Name<T>`, `view`):** **Later** — pinned standard-pack imports and explicit remappings already serve `std-order`, `std-part`, `std-time` and `std-decision` without generic instantiation machinery.
- **Custom literal types (`literal IPv4: Text`):** **Later** — pattern-refined scalar aliases and standard packs (`std.units`, `std.money`) cover current packs; user-defined lexical grammars with named subfields can arrive additively later.
- **Effect classes (`computes`, `reads`, `transacts`, `writes`):** **Later** — the compiler already blocks observations from feeding `check`/`require`, and full effect annotations add ceremony before packs use live observation streams widely.
- **Norms (`norm`):** **Later** — `warn` and published finding derivations already express non-blocking checks over observations; `norm` stays reserved until operational monitoring packs need a separate keyword.
- **Cross-pack exceptions (`exception <label> of other.Target`):** **Later** — ordering among competing foreign exceptions is still an open design point ([`v0.md`](v0.md#14-open-points-09-11) §14 point 5), and local `unless` plus extensible `Bool` derivations cover current packs.
- **`priority` decision-table policy:** **Not** — silently breaking ties by the declaration order of an output enum makes reordering an enum silently change rule outcomes; authors who want precedence write `table first` or ordered `unless` blocks.
- **Bounded search (`W110`):** **Later** — a solver offload in CI is an external analysis tool, not a language prerequisite, and example coverage (`W109`) already flags dead clauses in the first release.

### 6. Law text as a file

**Verdict: Later** — keep the first release to plain `.rezono` files with `@ source#locator` per version and exception ([`v0.md`](v0.md#5g-sources-and-interpretations) §5g) and `fragment_sha256` in [`contracts/source.yaml`](../../contracts/source.yaml), then add a literate module mode additively once prose-normalization and anchor hashing settle. In a literate module, statutory articles sit directly above their rules — each heading supplies the default `@` source locator and pins `fragment_sha256` of its UTF-8 prose bytes so an amended article flags every rule beneath it for review. Sketched on [`examples/zorgtoeslag-slice/rezono/allowance.rezono`](../../examples/zorgtoeslag-slice/rezono/allowance.rezono):

```markdown
## wzt#art-2.1 (sha256: <64-hex-fragment-digest>)
An insured person is entitled to a healthcare allowance if their joint income does not exceed the threshold.

    extend Household
      derived allowance: Cents = floor(yearly_amount / 1200) * 100
        unless not insured then 0

## wzt#art-2.2 (sha256: <64-hex-fragment-digest>)
No entitlement exists when joint income exceeds the income limit.

        unless joint_income > income_limit then 0
```

To support this, the reader in `rezono/src/` needs a small literate front-end that extracts indented/fenced Rezono blocks while preserving exact file line numbers and code-point offsets in `spans`, hashes each heading's prose bytes against `fragment_sha256` (warning or flagging stale rules on mismatch), and attaches the active heading's locator as the default `@` source on declarations and `unless` lines underneath.

### 7. Examples and comparison

**Verdict: In the first release** — both directly prove the value of executable rules to domain experts. First, `example` blocks inside a pack (`given` facts + `expect` values or `expect violation`, with optional `at` / `as known` context per [`v0.md`](v0.md#5e-testing) §5e) make every pack self-testing against the engines, and a CI coverage report (`W109`) warns about any version, `unless` line, table row or derivation that no example exercises. Second, a comparison query across two knowledge dates (e.g. comparing an `ask` `as known 2026-02-01` against `as known 2026-03-15`) reuses the existing publication difference and turning-point machinery (`rezono.turns/1`) to show exact change impact — which rows changed value or state and which amended rule or parameter caused the turn — before an amendment is approved.

### 8. Roles as declarations

**Verdict: Later** — keep access and review rights as explicit `Bool` derivations in `packs/std-access` during the first release, and introduce declarative `role` syntax as additive sugar once the full rights model stabilizes. Central read access ([`decisions/central-read-access.md`](../../decisions/central-read-access.md)) uses explicit `may_read(role, kind, element)` and `may_read_full(role, kind)` verified independently by `checker/rezono_checker/access.py`, while proposal and review rights (`may_propose`, `may_review`, `may_publish`, `may_execute`, anchored in [`contracts/change.yaml`](../../contracts/change.yaml) and [`contracts/proposal.yaml`](../../contracts/proposal.yaml)) are being finalized on the same foundation. A future `role analyst` block with `read`, `propose` and `review` clauses would lower deterministically to those exact `Bool` relations without altering the checker boundary; deferring the sugar avoids freezing syntax before review-rights rules have been exercised on real packs.

### 9. Small spelling improvements

- **Period shorthand (`valid 2026`, `valid 2026-03`):** **In the first release** — statutory parameters and annual facts almost always use full calendar years or months (every parameter in `examples/zorgtoeslag-slice` repeats `2025-01-01..<2026-01-01`); desugaring `valid 2026` to `valid 2026-01-01..<2027-01-01` is unambiguous, exact and removes boilerplate.
- **Digit grouping (`€ 38_520`, `2_400_000`):** **In the first release** — underscores between digits in numeric and money literals are purely lexical (stripped during parsing and normalized by the printer), zero semantic cost, and make monetary thresholds readable at a glance.
- **Leading dot for element lookup (`.pred`):** **Not** — [`docs/rezono/expressions.md`](expressions.md#5-name-resolution) §5 rule 2 already resolves bare names inside `where` and aggregates on the element first, raising `R011` only when a name exists in both element and outer scope, where `it.pred` disambiguates it. Adding `.pred` would introduce a second spelling for `it.pred` (breaking "one obvious way to write each thing" in [`v0.md`](v0.md#1-goals-and-limits) §1) for a rare collision case that explicit outer binders (`extend s: Service`) already prevent.

### 10. Around the language

**Small (ship with the first release):** generate a syntax-highlighting grammar (TextMate / Tree-sitter) directly from `rezono/src/`'s Ohm grammar so editor highlighting stays in lockstep with the reader, and expose the existing canonical printer (`rezono/src/print.ts`) as the single formatter (`rezono fmt`) so every pack has one layout and clean diffs. **Large (after the first release, named with what each needs):** *context lenses* for valid date, knowledge date and role (needs an LSP wired to a compiled manifest and role bundle to show active versions and readable/closed relations); *live example values* inline (needs incremental evaluation of `example` blocks mapped back to `rezono.module` expression spans); *margin coverage* (needs `W109` coverage results mapped to declaration and clause spans); *change-impact review view* (needs two-knowledge-date / proposal `rezono.turns/1` differences joined with rule spans); and a *prose reading view* (needs the canonical AST, `messages/<lang>.mf2` labels/sentences and `@` locators rendered as structured domain prose).

### 11. The first release

Making `rezono 1` the **first publicly released language** while keeping `rezono 0` as the internal workbench affects three places: (1) **Compiler:** the compiler still needs the version switch (`R027`, `R028`) to read `rezono 0` and `rezono 1` side by side during transition, but `rezono 0` carries no long-term external support burden once packs move; (2) **[`v0.md`](v0.md#4b-language-version-and-deprecation) §4b:** the external stability and phased-deprecation promise starts at `rezono 1`, so workbench cleanups (unifying `rule` and `derived`, dropping `priority` tables) do not ship with legacy deprecations on day one; (3) **Repo packs:** all packs in `examples/`, `packs/` and `run/packs/` migrate to `rezono 1` before tagging the first public release so no released pack teaches a superseded workbench rule syntax.

---

## Part C: Testing and choosing

### 12. Cold-read check

Before merging this proposal, an independent reviewer unfamiliar with Rezono will read the following five representative derivations from [Section 3](#3-the-platform-trial-examplesplatformrulescoredl) and state in one sentence per derivation what it means. All five sentences will be recorded verbatim below, including any misunderstandings.

1. `needs(a: Service, f: Function): Service` (with `chosen`) — multi-key functional derivation with explicit domain `over asks(a, f)`, `.one()` and `unless` testing `is n/a`.
2. `Product.newest_day: Int` — derived property on a kind using `.where(...)` and `.max(...)`.
3. `Service.runs: Release` (with `Service.pin`) — derived property combining `.where(...).one()` with `unless` precedence.
4. `flow_from_step(a: Service, b: Service): Int` — multi-key functional arithmetic derivation over `over needs_service(a, b)`.
5. `unauthenticated_target(target: Service, fn: Function): Bool` — `Bool` derivation combining `.where(...).any(...)`, enum comparison and negation of a derived Boolean property.

_Pending cold-read review before merge._

---

### 13. Two paths and recommendation

The repository currently holds **91 tracked `.dl` rule files** across its packs (53 in `examples/`, 25 in `packs/`, 13 in `run/`; 118 total including test fixtures), and **none** of them has been converted to native rules yet. Schemas, facts, parameters and calculations are already being migrated in syntax that carries forward unchanged into `rezono 1`. That leaves two paths for the rules:

| Aspect | Path 1: Convert twice (first `rezono 0`, then `rezono 1`) | Path 2: Convert once (directly to `rezono 1`) |
|---|---|---|
| **Migration cost** | Convert all 91 `.dl` files, parity tests and snapshots to `rezono 0` `rule ... when ...`, then rewrite and re-verify functional rules, `ambiguous_*`/`unmet_*` findings and `it.` aggregates a second time for `rezono 1`. | Finish schema/fact/parameter/calculation conversion on `rezono 0`, keep `.dl` files as the live oracle while building `rezono 1` functional lowering, then convert all 91 `.dl` files once into `rezono 1`. |
| **Upfront engineering** | None beyond existing `rezono 0` native-rule lowering (`decisions/language-native-rules.md`). | Requires (a) Feldera calculation state/witness verification (Feldera rule 5), (b) compiler version switch (`rezono 1`), and (c) co-located functional derivation IR, checker and engine lowering ([Section 4](#4-underlying-form-checker-and-engine-view-analysis)). |
| **Effect on the native-rules completion criterion** ("all pack rules in native Rezono syntax, no `.dl` files or Datalog `|` blocks") | Met earlier in `rezono 0`, but in workbench syntax that will be superseded before the first public release. | Met later — after `rezono 1` lowering lands — directly in the released language, with zero throwaway rule conversions. |

**Recommendation: choose Path 2 (convert rules once, directly to `rezono 1`).** Continuing schema, fact, parameter and calculation conversion on `rezono 0` preserves all current momentum (every one of those declarations keeps its form in `rezono 1`), while holding off on hand-converting 91 `.dl` files into `rezono 0` avoids doing the largest mechanical and semantic migration twice. The saved effort funds the exact prerequisites `rezono 1` needs anyway: verifying current calculation states and witnesses on Feldera, adding the compiler version switch, and implementing co-located functional views. (Path 1 remains the fallback only if an intermediate `rezono 0`-only milestone with native Datalog-equivalent rules is required before the first public release.)
