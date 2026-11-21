---
decider: [language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: language-requirements
---

# Rezono 1: existential and cardinality requirements (`require`)

`rezono 1` adds a first-class declarative requirement construct for existential and cardinality obligations: **"whenever pattern P holds, pattern Q must also exist, optionally with a count bound (`at least N`, `at most N`, or `exactly N`)."**

Across existing repository packs (`examples/`, `run/`, `build/`, `epoch/`, `packs/`), this exact pattern is currently hand-encoded in dozens of ad-hoc `*_missing*`, `*_without_*`, `unmet_*`, and `count`-guard Datalog rules and Python assertions. Making existential and cardinality requirements a native `rezono 1` declaration gives them:

- one readable, domain-facing syntax with zero new hard expression keywords;
- sound four-state semantics (`known`, `not_applicable`, `unknown`, `invalid`) that separate **proven monotone bounds** from **exact counting** under incomplete (`world open`) registers: never silently passing or falsely violating when an exact count requires a complete sweep, while proving lower bounds (`exists` / `at least N`) from `N` distinct confirmed witnesses and upper/exact-bound violations (`at most N` / `exactly N`) from `N + 1` distinct confirmed witnesses without waiting for a complete sweep;
- direct lowering into `rezono.rules/2` with independently verified witnesses carrying distinct identities, scope, and time (plus the completeness coverage premise `<cov>` whenever a complete sweep is load-bearing);
- direct alignment with norm standing ([`decisions/platform-norm-standing.md`](platform-norm-standing.md)) and a sound foundation for future minimal additive repair (the chase).

Nothing in this decision changes `rezono 0` (`rezono.module/1`–`/4`, `rezono.rules/1`, `rezono.calc/1`), existing module-level check expressions (`check`/`warn`/`require [name:] <expr>`), or single-kind conditional checks (`require <name> when <expr> then <expr>` inside `kind`; [`decisions/language-checks.md`](language-checks.md)).

---

## 1. Syntax in `rezono 1`

A module-level requirement declaration uses `require` with typed trigger parameters and an indented clause block (parallel to `step` in [`decisions/language-safe-steps.md`](language-safe-steps.md) and module-level `derived` in [`decisions/language-rezono-1.md`](language-rezono-1.md)):

```rezono
-- Multi-clause existential: every rack in the cage has both feed A and feed B
require rack_dual_feed(r: Rack)
  when r.in_cage = yes
  exists feed_a: PowerFeed where feed_a.rack = r and feed_a.bus = bus_a
  exists feed_b: PowerFeed where feed_b.rack = r and feed_b.bus = bus_b
  means "{$r} in cage must have both feed A and feed B." @ dc-policy#power-1

-- Cardinality lower bound: every critical service runs at least 3 healthy replicas
require service_ha(s: Service)
  when s.tier = critical
  exists at least 3 r: Replica where r.service = s and r.healthy = yes
  means "{$s} must run at least 3 healthy replicas." @ slo#ha-3

-- Exact and upper cardinality bounds
require single_primary(c: Cluster)
  when c.active = yes
  exists exactly 1 n: Node where n.cluster = c and n.role = primary

require bounded_egress(s: Service)
  when s.isolated = yes
  exists at most 2 e: EgressRule where e.service = s

-- Unconditional single-kind existentials (`when` omitted => triggers for every element of the kind)
require fact_has_origin(f: FactRecord)
  exists o: Origin where o.fact = f

require conclusion_has_witness(c: Conclusion) invariant
  exists w: Witness where w.conclusion = c

-- Multi-key requirement with mandatory closed `over` domain and relation target
require deployment_in_cmdb(e: CmdbExport, s: Service, c: Cluster)
  over expected_cmdb_placement(e, s, c)
  exists o: CmdbObservation where o.export = e and o.service = s and o.cluster = c
  means "{$s} on {$c} must appear in CMDB export {$e}." @ ops#cmdb-1

require service_provider_exists(a: Service, f: Function)
  over asks(a, f)
  exists row in provides where row.function = f
```

### Grammar and zero keyword collisions

In `rezono/src/module-requirement.ts` (registered in `rezono/src/module-components.ts` before `check`, active in `rezono 1` / `rezono.module/5` only):

```ohm
RequirementLine = kw<"require"> rName "(" NonemptyListOf<RuleColumn, ","> ")" RequirementOption*
RequirementOption = kw<"invariant">  -- invariant
RequirementClauseLine = RequirementOverLine | RequirementWhenLine | RequirementExistsLine | RuleMeansLine
RequirementOverLine = DerivedOver
RequirementWhenLine = when Expr
RequirementExistsLine = kw<"exists"> RequirementBound? rName ":" RuleType (where Expr)?   -- kind
                      | kw<"exists"> RequirementBound? rName in RuleRef (where Expr)?     -- relation
RequirementBound = at kw<"least"> digits ~tokCont       -- at_least
                 | at kw<"most"> digits ~tokCont        -- at_most
                 | kw<"exactly"> digits ~tokCont        -- exactly
```

- **No collision with existing `require` forms:**
  - Module-level check `require active: shelf.open is known` has `:` after the name (`Check`).
  - Module-level call check `require isolated(tenant-a, management)` has untyped expression arguments with no `: Type` inside `(...)` (`Check`).
  - Kind-level conditional check `require rule_1 when membership = adult then home_branch is known` has `when` after the name and lives only inside `kind` (`ConditionalCheckLine`).
  - Requirement declarations uniquely begin with `require <name>(<p1>: <T1>, ...)` with typed `RuleColumn` parameters and an indented clause block.
- **Zero new hard expression keywords:** `exists`, `least`, `most`, and `exactly` are recognized solely inside the block-scoped `RequirementClauseLine` rule (matching `forbid`, `within`, `effect`, `confirm`, and `token` inside `StepClauseLine` in `rezono/src/module-step.ts`). The hard expression keyword set ([`decisions/language-contextual-keywords.md`](language-contextual-keywords.md)) stays unchanged.
- **Explicit binders only:** Following [`decisions/language-rezono-1-refinements.md`](language-rezono-1-refinements.md) §1, every `exists` clause introduces one explicit binder (`r: Replica` for a kind target, or `row in provides` for a `Bool` relation target). No implicit existential variables are introduced in `when` or `where`. Re-binding a trigger parameter name in `exists` is refused with `R011`.
- **Cardinality bounds:**
  - Omitted bound means pure existential (`at least 1`).
  - `at least N` requires `N >= 1` (`at least 0` is refused with `R000`).
  - `at most N` and `exactly N` admit any natural integer `N >= 0` (`exactly 0` expresses scoped non-existence cleanly).
  - Non-integer or negative bounds fail parsing with `R000`.
- **Structural validation at read time (`R000`):**
  - At least one `exists` clause is mandatory; a `require` block with no `exists` clause is refused with `R000`.
  - At most one `over`, one `when`, and one `means` line per `require`; duplicates are refused with `R000`.
  - Distinct trigger parameter names are required; duplicate parameter names are refused with `R000`.
  - A multi-key requirement (2 or more parameters) MUST declare `over <relation>(p1, ..., pm)` whose arguments match the declared parameters (identical to multi-key functional `derived` in `rezono/src/module-derived.ts`); omitting `over` on a multi-key requirement is refused with `R000`.
  - A `require` block declaration inside a `rezono 0` module is refused with `R000`.

### Canonical JSON form (`rezono.module/5`)

`contracts/rezono-module.yaml` extends `Rezono1Module.decls` with `RequirementDecl`:

```json
{
  "require": "service_ha",
  "params": [{"name": "s", "type": "Service"}],
  "when": {"cmp": ["=", {"path": ["s", "tier"]}, {"path": ["critical"]}]},
  "exists": [
    {
      "binder": "r",
      "kind": "Replica",
      "bound": {"op": "at_least", "count": "3"},
      "where": {
        "and": [
          {"cmp": ["=", {"path": ["r", "service"]}, {"path": ["s"]}]},
          {"cmp": ["=", {"path": ["r", "healthy"]}, {"path": ["yes"]}]}
        ]
      }
    }
  ],
  "means": "{$s} must run at least 3 healthy replicas.",
  "source": "slo#ha-3"
}
```

- Every count in `bound.count` is `DecimalText` (decimal string, never a JSON number), preserving canonical JSON (`contracts/rezono-module.yaml`).
- Absent optional members (`over`, `when`, `options`, `bound`, `where`, `means`, `source`) are omitted (never `null`).
- Each `exists` entry carries `binder`, exactly one of `kind` or `relation`, optional `bound` (`op` in `at_least | at_most | exactly`, `count: DecimalText`), and optional `where` (`Expr`).
- Canonical printing in `rezono/src/module-requirement.ts` round-trips losslessly through `parseModule` and `moduleFromJson`.

---

## 2. Four-state semantics and sweep completeness

Every requirement `require <name>(k1: T1, ..., km: Tm)` has a **mandatory finite closed domain** `D` (the parameter's kind `K` when `m = 1` without `over`, or the `over D(k1, ..., km)` relation). An `open` trigger kind or `open` `over` relation is refused at compile time with `functional_open_domain` ([`decisions/language-rezono-1.md`](language-rezono-1.md) §2).

For each key tuple `k` in `D`, evaluation proceeds across all four states of Rezono's value lattice (`known`, `not_applicable`, `unknown`, `invalid`; [`docs/rezono/expressions.md`](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) Appendix A):

### Step 1: Trigger evaluation (`when P(k)`)

If `when` is omitted, the trigger is `known true` for every `k` in `D`. Otherwise evaluate `P(k)`:

| Trigger `P(k)` | Requirement outcome `<name>(k)` | Emits `<name>_violation`? |
| --- | --- | --- |
| `known false` or `not_applicable` | `not_applicable` (reason `no_match`) | No (0 findings) |
| `unknown <r>` | `unknown <r>` | No (never a false violation or false pass) |
| `invalid <r>` | `invalid <r>` | No (preserves conflict/invalid witness) |
| `known true` | Proceed to Step 2 (evaluate every `exists` clause) | Depends on Step 2 |

### Step 2: Evaluating each `exists` clause `c_i` under world and sweep completeness

Let target `Q` be a declared kind `Kind` or `Bool` relation `rel`, with optional filter predicate `W(k, x)` (default `true`).

1. **World and sweep completeness of `Q`** (following [`decisions/language-rezono-1-defaults.md`](language-rezono-1-defaults.md) §2):
   - **`world closed`:** `Q` is complete for every key `k`.
   - **`world open, complete by <cov>`:** `Q` is complete for key `k` **if and only if** the coverage relation `<cov>` holds for the scope columns bound by `k` (and any equality constraints in `W`). Outside `<cov>`, `Q` is incomplete with core reason **`incomplete_read`**.
   - **`world open` (no `complete by`):** `Q` is incomplete everywhere with evaluation reason **`open_world`**.
2. **Evaluating `W(k, x)` and candidate identity over rows `x` of `Q`:**
   - Following [`decisions/language-rezono-1-refinements.md`](language-rezono-1-refinements.md) §3.1 (`.count(pred)` equals `.where(pred).count()`), for each observed row `x` of `Q`:
     - `W(k, x) = known true` -> `x` is a confirmed matching candidate.
     - `W(k, x) = known false` or `not_applicable` -> `x` is excluded (contributes `0`).
     - `W(k, x) = unknown <r>` -> membership of `x` is undecided (`unknown <r>`).
     - `W(k, x) = invalid <r>` -> membership of `x` is in conflict / invalid (`invalid <r>`).
3. **Conflict precedence (checked strictly before proving any bound):**
   - If any candidate row `x` of `Q` in scope `k` has `W(k, x) = invalid <r>`, **or** any candidate identity record in scope `k` is in conflict (for example `invalid multiple_values` from competing `.one(...)` identity claims, or `std-identity` `disputed` / `representatives_disagree` / `identity_conflict`), the clause MUST evaluate to **`invalid <r>`** and emit zero rows in `<name>_violation`.
   - A conflicting trigger, candidate, or identity record MUST NEVER be silently dropped and MUST NEVER be masked by other matching witnesses to claim `known true` (`at least N`) or `known false` (`at most M` / `exactly M`).
4. **Distinct canonical identities and possibly-duplicate records:**
   - Cardinality bounds count **provably distinct canonical identities**, never raw duplicate records or uncanonicalized aliases.
   - For a closed-identity kind without alias resolution, each distinct element identifier of the kind is a distinct canonical identity.
   - When records may alias the same entity (for example via `std-identity` `same_as` / `representative`, or via an explicit canonical entity kind / canonical identity derivation such as `canonical_entity = IdentityClaim.where(observation = r).one(entity)`):
     - Two records proven to refer to the same canonical identity collapse to **one** entity and MUST NOT be double-counted toward `N` distinct witnesses to prove `at least N` or toward `N + 1` distinct witnesses to violate `at most N` or `exactly N`.
     - Records with **unproven distinctness** (possibly duplicate records — for example `std-identity` `representative_not_recorded`, or missing/unresolved canonical identity yielding `unknown`, or unclosed alias equivalence) MUST NOT be counted as separate witnesses toward `N` or `N + 1`. Only records with proven distinct canonical identities contribute to `confirmed_distinct(k)`.
     - If `confirmed_distinct(k)` from the provably distinct subset alone does not settle the bound (or when exact counting is required and any candidate in scope has unproven distinctness), the clause MUST remain **`unknown`** (never falsely proving satisfaction or violation).
5. **Separating a proven bound from an exact count:**
   - Let `confirmed_distinct(k)` be the number of provably distinct canonical entities in `Q` for scope `k` with `W(k, x) = known true` (once Step 3 confirms there is no `invalid` conflict in scope `k`).
   - Under an incomplete (`world open`) register without conflict, observing additional unseen rows (or resolving `unknown` predicates / uncanonicalized records) can only **increase** — never decrease — the true distinct matching count (`true_count >= confirmed_distinct(k)`). Therefore a **monotone proven bound** does not require an exact count or a complete sweep, whereas any judgment that depends on ruling out unseen rows requires an **exact count** (a complete sweep with all candidate predicates decided and all identities resolved):
     - **Lower bound (`exists` / `at least N`, `N >= 1`):** Omitted `exists` is semantically identical to `at least 1`. On an incomplete register without conflict, `1` certain match proves **both** `exists` and `at least 1` (`known true`), and `N` distinct confirmed witnesses (for example `3` distinct confirmed replicas for `at least 3`) prove `at least N` (`known true`) — a complete sweep is **not** required once `N` distinct confirmed witnesses exist. Only when fewer than `N` distinct confirmed witnesses are observed (for example `2` observed replicas for `at least 3`) without a complete sweep does the outcome remain **`unknown incomplete_read`** (for `complete by <cov>` outside `<cov>`) or **`unknown open_world`** (for plain `world open`), with zero violation rows. Proving violation (`known false`, deficit `< N`) requires an exact count (complete sweep, all candidates decided and distinct).
     - **Upper bound (`at most N`, `N >= 0`):** On an incomplete register without conflict, `N + 1` distinct confirmed witnesses (for example `5` distinct confirmed replicas for `at most 4`) prove violation (**`known false`** + finding in `<name>_violation`) even without a complete sweep, because unseen rows can never reduce the count back to `<= N`. Observing `<= N` distinct confirmed witnesses without a complete sweep MUST remain **`unknown incomplete_read`** (or **`unknown open_world`**), with zero violation rows. Proving satisfaction (`known true`, `observed <= N`) requires an exact count (complete sweep, all candidates decided and distinct).
     - **Exact bound (`exactly N`, `N >= 0`):** On an incomplete register without conflict, `N + 1` distinct confirmed witnesses prove violation (**`known false`** + finding in `<name>_violation`) even without a complete sweep. Proving satisfaction (`known true`, `observed = N`) or deficit violation (`known false`, `observed < N`) requires an exact count (`N` resp. `< N` distinct confirmed witnesses **and** a complete sweep, with all candidates decided and distinct); observing `<= N` without a complete sweep MUST remain **`unknown incomplete_read`** (or **`unknown open_world`**), with zero violation rows.

   | Bound | Incomplete register (`!cov` or plain `world open`), no conflict | Complete register (`world closed` or `cov` holds), all candidates decided & distinct, no conflict | Complete register with undecided candidate (`W = unknown <r>`) or unproven distinctness, no conflict |
   | --- | --- | --- | --- |
   | `exists` / `at least 1` | `confirmed_distinct >= 1` -> **`known true`**; `0` -> **`unknown incomplete_read`** (or `open_world`) | `observed >= 1` -> **`known true`**; `0` -> **`known false`** (violated, cites `<cov>` if `complete by`) | `confirmed_distinct >= 1` -> **`known true`**; `0` -> **`unknown <r>`** |
   | `at least N` (`N >= 1`) | `confirmed_distinct >= N` -> **`known true`**; `< N` -> **`unknown incomplete_read`** (or `open_world`) | `observed >= N` -> **`known true`**; `< N` -> **`known false`** (violated, cites `<cov>` if `complete by`) | `confirmed_distinct >= N` -> **`known true`**; `< N` -> **`unknown <r>`** |
   | `at most N` (`N >= 0`) | `confirmed_distinct >= N + 1` -> **`known false`** (violated); `<= N` -> **`unknown incomplete_read`** (or `open_world`) | `observed <= N` -> **`known true`** (cites `<cov>` if `complete by`); `>= N + 1` -> **`known false`** (violated) | `confirmed_distinct >= N + 1` -> **`known false`** (violated); `<= N` -> **`unknown <r>`** |
   | `exactly N` (`N >= 0`) | `confirmed_distinct >= N + 1` -> **`known false`** (violated); `<= N` -> **`unknown incomplete_read`** (or `open_world`) | `observed = N` -> **`known true`** (cites `<cov>` if `complete by`); `!= N` -> **`known false`** (violated; deficit `< N` cites `<cov>` if `complete by`) | `confirmed_distinct >= N + 1` -> **`known false`** (violated); `<= N` -> **`unknown <r>`** |

   This preserves [`decisions/language-rezono-1-defaults.md`](language-rezono-1-defaults.md) §2: `complete by <cov>` guards every exact count and absence conclusion (`observed < N`, `observed <= N`, `observed = N`, `!exists`) where unseen rows could overturn the judgment, while never blocking a monotone proven bound (`confirmed_distinct >= N` for `at least N` / `exists`, or `confirmed_distinct >= N + 1` falsifying `at most N` / `exactly N`) established by provably distinct, conflict-free witnesses.

### Step 3: Combining multiple `exists` clauses

When a `require` declares clauses `c_0, ..., c_{r-1}`:

- Every clause `c_i` that evaluates to **`known false`** independently emits its own finding row in `<name>_violation` (so e.g. a caged rack missing both feed A and feed B reports both missing obligations with their individual witnesses).
- The overall outcome `<name>(k)` combines clause outcomes using Rezono's four-state conjunction `and` (Appendix A.1, with Appendix A.4 deterministic reason tie-breaking):
  - All clauses `known true` -> `("known", "", "true")`.
  - Any clause `known false` -> `("known", "", "false")`.
  - Otherwise, highest state among remaining clauses (`invalid` > `unknown`, UTF-8 least reason code on ties).

---

## 3. Lowering to `rezono.rules/2`, witnesses, and engines

The compiler (`compiler/rezono_compiler/rezono_requirements.py`, invoked from `pack.py` alongside `rezono_derived.py`) lowers every `require <name>(k1: T1, ..., km: Tm)` in `rezono.module/5` directly into **`rezono.rules/2`** (never silently dropped and never falling back to legacy `.dl`):

### Generated relations in `rezono.rules/2`

1. **Outcome relation `<name>`** (`role: functional`):
   - `domain`: `<domain>` (closed single-key kind or declared `over` relation; open domain refused with `functional_open_domain`).
   - `key`: `[k1: T1, ..., km: Tm]`.
   - `value`: `{"name": "value", "type": "boolean"}`.
   - `world`: `"closed"`, `conflict_policy`: `"publish"`.
   - One row `(k1, ..., km, state, reason, value)` for every key in `<domain>`, matching the exact four-state table in Section 2.
2. **Finding / violation relation `<name>_violation`** (`role: derived`):
   - `world`: `"closed"`.
   - `invariant`: `true` if `invariant` is written on the `require` header, else `false` (by default unmet requirements publish as witnessed findings rather than silently dropping or halting an entire epoch; packs that want epoch-blocking enforcement write `require <name>(...) invariant`).
   - `key`: `[k1: T1, ..., km: Tm, clause: integer, target: string, bound: string, observed: integer]`, where:
     - `k1, ..., km` identify the triggering subject/key tuple;
     - `clause` is the 0-based index of the unmet `exists` clause (`0`, `1`, ...);
     - `target` is the canonical snake_case name of the required kind or relation (e.g. `"power_feed"`, `"replica"`, `"origin"`, `"provides"`);
     - `bound` is the canonical bound tag (`"at_least:1"` when omitted, `"at_least:N"`, `"at_most:N"`, `"exactly:N"`);
     - `observed` is the observed count of provably distinct matching identities (`0`, `1`, `2`, `5`, ...).
3. **Helper distinct-witness match relations** (strictly lower stratum than `<name>` and `<name>_violation`, non-recursive): one scoped match relation `M` per `exists` clause binding `(k..., identity)` for provably distinct confirmed rows satisfying `W(k, x) = known true`. Omitted `exists` lowers uniformly as `at least 1` over `M` so `exists` and `at least 1` never diverge in semantics or witness shape.

### Verified witnesses (`contracts/proof.yaml` and `checker/rezono_checker/`)

Every proven outcome row in `<name>` (`(k..., "known", "", "true")`) and every violation row in `<name>_violation` (`(k..., clause, target, bound, observed)`) carries a complete proof verified independently by `checker/rezono_checker/`:

- **Trigger and scope premises:** positive premises proving `k ∈ domain` and every base/derived atom establishing `when P(k) = true`.
- **Distinct identities, scope, and time (for proven bounds):**
  - For every proven lower bound (`known true` on `exists` / `at least 1` / `at least N`, e.g. `1` match proving `exists` and `at least 1`, or `3` distinct confirmed replicas proving `at least 3`) and every proven upper/exact-bound violation (`known false` on `at most N` / `exactly N` with `confirmed_distinct >= N + 1`, e.g. `5` distinct confirmed replicas proving violation of `at most 4`), the proof carries the count aggregate over `M` (`relation = M`, `group_key = [k...]`, `count = confirmed_distinct`, `contributors_sha256`, `result = "known:<count>"`), where `contributors_sha256` commits to the exact sorted set of `confirmed_distinct` distinct witness rows in `M`.
  - Every contributing row in `M` for scope `k` carries its own independently checker-verified proof citing the witnessing record's **distinct canonical identity**, **scope**, and **observation/evaluation time**.
- **Completeness premise (only when load-bearing):**
  - When `Q` is `world open, complete by <cov>`, the positive coverage premise `<cov>(...)` MUST appear in every proof whose conclusion relies on exact counting: deficit violation (`observed < N` for `exists` / `at least N` / `exactly N`) and upper/exact satisfaction (`observed <= N` for `at most N`, `observed = N` for `exactly N`). Filtered roles must read `<cov>` in full per [`decisions/witnessed-read-completeness.md`](witnessed-read-completeness.md).
  - When a monotone bound is proven directly from `N` (or `N + 1`) distinct confirmed witnesses on an incomplete register without needing a complete sweep, `<cov>` is **not** required and MUST NOT be fabricated.
- **Missing-pattern / exact-count evidence:**
  - For deficit violations (`observed = 0` or `observed < N` under a complete sweep / closed world): count aggregate evidence over `M` (`relation`, `group_key`, `count = observed`, `contributors_sha256`, `result`, or negative premise on the clause match helper when `observed = 0`) plus the bound comparison condition (`observed < N`, `observed > N`, or `observed != N`).
- **Bundle metadata (`bundle/schema-bundle.json`):** `means` lowers to the rule message in the pack's default language and `@` lowers to `source` on the requirement's bundle rule entries (matching `derived` in [`decisions/language-rezono-1.md`](language-rezono-1.md) §2).

### Engine invariants (DuckDB, Feldera, Soufflé)

- **Never inside recursion:** requirements sit strictly above their domain, trigger, target, and coverage strata; neither `<name>` nor `<name>_violation` is ever emitted inside `DECLARE RECURSIVE VIEW`.
- **Co-located view:** `<name>` emits one `NOT NULL` co-located view `(k..., state, reason, value)` on DuckDB and Feldera (classified as `"functional_aggregate"` when counting or `"functional"` otherwise in `rules_split.views_by_kind`), and `<name>_violation` emits one plain derived view (weight 1).
- **Access boundary:** requirements do not enter `may_read` / `may_read_full` definitions (preserving the access trust boundary in [`decisions/language-rezono-1.md`](language-rezono-1.md) §4).

---

## 4. Relationship to norms (`✕` / violated standing)

In Rezono's norm model ([`decisions/platform-norm-standing.md`](platform-norm-standing.md)), a norm's standing for a subject is only `known` (`✓` pass / `✕` fail) when independent coverage establishes that no unseen evidence can overturn the judgment; incomplete coverage MUST yield `unknown` (`?`), and conflicting grounds stay visible.

`require` is the language-level building block for structural and operational norm obligations:

| Requirement state `<name>(k)` | Norm standing correspondence | Witness & visibility |
| --- | --- | --- |
| `known true` | Satisfied (`✓` / pass) | Positive trigger + distinct witness identities, scope, and time (and coverage premise `<cov>` whenever an upper or exact bound makes a complete sweep load-bearing). |
| `known false` | Violated (`✕` / fail) | Finding row in `<name>_violation` with verified witness citing trigger, distinct witness identities/scope/time (for `at most N` / `exactly N` excess violations even without coverage), or missing target/deficit plus coverage premise `<cov>` (when complete sweep is load-bearing). |
| `unknown incomplete_read` / `unknown open_world` | Incomplete coverage (`?` / unknown) | Explicit `unknown` row in `<name>`; zero rows in `<name>_violation` (matches `authority-coverage-incomplete` / `register-coverage-incomplete`). |
| `not_applicable no_match` | Out of norm scope | Explicit `not_applicable` row in `<name>`; zero rows in `<name>_violation`. |
| `invalid <reason>` | Conflicting / invalid grounds | Explicit `invalid` row in `<name>` carrying every competing candidate witness (matches `norm_ruling_conflict` visibility). |

Packs that derive standing purely from facts and verified sweeps can author obligations directly as `require` declarations. Packs that combine obligations with dated human rulings (`std-decision`, as in [`decisions/platform-norm-standing.md`](platform-norm-standing.md)) can read `<name>` and `<name>_violation` directly beside authoritative rulings. When the reserved `norm` keyword ([`docs/rezono/v0.md`](../docs/rezono/v0.md#checks-norms-and-requirements) §5) is activated after Release 1, it reuses this exact four-state requirement lowering and `complete by` coverage model.

---

## 5. Relationship to minimal additive repair (the chase)

Every `require` declaration is mathematically a **tuple-generating dependency (TGD)** or **counting TGD**:

$$\forall \vec{k} \in D.\; P(\vec{k}) \;\longrightarrow\; \exists^{\mathrm{bound}}\, x \in Q.\; W(\vec{k}, x)$$

This makes the exact same declaration serve two roles without duplicating rules:

1. **Declarative verification in `rezono 1` (Release 1 / M3):** `require` is strictly declarative and read-only. Evaluation never mutates facts or invents rows; it produces the four-state outcome `<name>` and witnessed findings `<name>_violation`.
2. **Minimal additive repair (the chase, post-M3):**
   - Every violation row `(k..., clause, target, bound, observed)` in `<name>_violation` with a lower-bound deficit (`at_least:N` with `observed < N`, or `exactly:N` with `observed < N`) directly specifies an active chase trigger: target kind `target`, required equality bindings from `W(k, x)` (such as `rack = r, bus = bus_b` or `service = s, healthy = yes`), and exact additive deficit `N - observed`.
   - A future repair planner built on `suppose` and safe `step` declarations ([`decisions/language-safe-steps.md`](language-safe-steps.md)) can synthesize the minimal additive `+ Target fresh_id { ... }` insertion candidates (using labeled nulls for unconstrained required slots) directly from the requirement AST and violation witness.
   - **Soundness guards inherited automatically:**
     - `unknown` rows (incomplete sweeps) **never** trigger repairs: you must acquire a complete sweep rather than inserting duplicate infrastructure because a collector reading was missing.
     - Upper-bound violations (`at_most:N` with `observed > N`, or `exactly:N` with `observed > N`) cannot be repaired additively; the `bound` and `observed` columns distinguish additive deficits from retraction/deduplication obligations immediately.
     - Any future chase runner will enforce acyclicity (or explicit step bounds) to preserve Rezono's termination invariant.

---

## 6. Repository inventory of implicit requirements

Scanning `examples/`, `run/`, `build/`, `epoch/`, and `packs/` identifies concrete implicit existential and cardinality requirements currently written as ad-hoc Datalog `!has_*` / `count` rules or Python checks. Per-pack conversion waits on the seven M3 language building blocks in Section 7 and aligns with the single-pass `rezono 1` pack conversion rollout ([`decisions/language-rezono-1.md`](language-rezono-1.md) §8 step 5):

| Area | Location | Current implicit rule / check | Requirement form |
| --- | --- | --- | --- |
| `packs/std-decision` | `packs/std-decision/rules/decision.dl` (`in_force_without_decider`, `in_force_without_start`, `withdrawn_without_start`) | `@absence` / `!has_*` negations checking every in-force decision has a decider and start date, and every withdrawn decision has a start date | Existential (`at least 1`) over open/closed slots |
| `packs/std-review` | `packs/std-review/rules/evidence.dl` (`evidence_missing`), `policy.dl` (`unreviewed_required`, `review_phase_ambiguous`) | `!evidence_passed` for required `(change, kind, sha)`, `!change_accepted` for required changes, uniqueness of review phase | Existential (`at least 1`) + exact cardinality (`exactly 1`) |
| `packs/std-budget` | `packs/std-budget/rules/budget.dl` (`budget_missing_head`) | `!has_head_ceiling` / `!has_head_observed` for every active budget cell | Existential (`at least 1`) |
| `packs/std-loop` | `packs/std-loop/rules/flow_witness.dl` (`flow_case_witness_count`, `flow_case_incomplete`), `complete_sweep.dl` (`sweep_node_report_count`) | Exact count check: every declared flow case requires `exactly 1` probe witness and `exactly 1` Hubble witness; complete sweep requires every admitted member covered | Exact cardinality (`exactly 1`) + multi-clause existential |
| `packs/std-time` | `packs/std-time/rules/time.dl` (`extension_without_end`) | `@invariant` checking every interval extension has an end bound | Existential (`at least 1`) with `invariant` |
| `examples/platform` | `examples/platform/rules/core.dl` (`unmet_need`, `unverified_supply`, `unauthenticated_target`) | `providers = 0`, `!verified(s)`, `!authenticates(target)` | Existential (`at least 1`) |
| `examples/platform` | `examples/platform/rules/cmdb_reference.dl` (`cmdb_missing_placement`, `cmdb_missing`, `cmdb_unknown`) | Hand-written `cmdb_covered` + `!cmdb_reported` split vs `!cmdb_covered` -> `cmdb_unknown` | Existential over `world open, complete by cmdb_covered` |
| `examples/platform` | `examples/platform/rules/management_backup.dl` (`backup_plan_has_copy`, `backup_inventory_complete`, `managed_backup_state`) | Hand-written completeness check for backup copy existence per plan | Existential over `world open, complete by backup_inventory_complete` |
| `examples/platform` | `examples/platform/rules/tenant_capacity.dl` (`capacity_period_missing_reading`) | `capacity_expected_member(_, p, t), !capacity_tenant_reading(p, t)` | Existential over receipt-scoped expected members |
| `examples/platform` | `examples/platform/rules/dependency_gaps.dl` (`dependency_gap`, `dependency_gap_unknown`, `missing_pair_domain`), `product_succession.dl` (`successor_unresolved`, `successor_uncovered_at`), `product_licence.dl` (`product_has_licence_gap`) | Hand-written existence + domain-unknown splits across providers, successors, and licence notices | Existential with four-state `unknown` propagation |
| `examples/subsidy-scheme` | `examples/subsidy-scheme/rules/assessment.dl` (`income_not_received`, `quote_missing`) | `!has_income_statement(h)` (open world -> `unknown`), `!has_quote(a)` | Existential over open/closed kinds |
| `run/packs/cluster-shape` | `run/packs/cluster-shape/rules/cluster_shape.dl` (`shape_problem` `"no_controller"` and `"count"`, `ceph_device_count`) | `!has_controller(c)` and `n = count : { valid_sku(c, s, _) }, n != q` | Existential (`at least 1`) + cardinality (`exactly N` / `at least 3`) |
| `run/packs/offer-selection` | `run/packs/offer-selection/rules/preflight.dl`, `allocation.dl` (`alloc_capacity_gap`, `allocation_limit_exceeded`) | Missing observed stock/price (`unknown`) and capacity/supplier count bounds | Existential + cardinality (`at least N` / `at most N`) |
| `run/packs/invoice-drift` | `run/packs/invoice-drift/rules/reconciliation.dl` (`rated_gap`, `billed_gap`, `forecast_gap`, `cap_gap`) | Count-based completeness checks across forecast/usage/billed lines | Cardinality + existential over scoped billing observations |
| `run/packs/provider-terms` | `run/packs/provider-terms/rules/order_guarantee.dl` (`order_has_valid_quote_policy`, `no_guarantee`) | Existence of a single non-conflicting `quote_policy` per order | Cardinality (`exactly 1`) with conflict visibility |
| `run/*.py` | `run/closed_month.py`, `run/effective_quote.py`, `run/offline_replay.py` | Python `ValueError` checks for missing plan hashes, missing SKU prices, and missing/ambiguous editions | Existential / uniqueness assertions |
| `build/rules` | `build/rules/selection.dl` (`build_full_selection`), `claim_release.dl` (`build_claim_release_pending`) | `!build_verified_cut(run)`, `!build_valid_dependency`, `!build_path_read`, missing readback receipt | Existential over receipt-covered build scope |
| `epoch/rules` | `epoch/rules/gates.dl` (`!epoch_has_run_check`, `!epoch_has_role_check`), `publish.dl` (`epoch_role_not_allowed`, `epoch_has_allowed_role`) | Every required run/role check must have a recorded sourced verdict; at least one allowed role and zero disallowed roles | Existential (`at least 1`) + universal/non-existence (`exactly 0`) |

---

## 7. Tests (`M3`)

Seven focused, independent, behavioral `M3` tests specify this decision:

| Test | File | What it verifies |
| --- | --- | --- |
| 1. Parsing & diagnostics | `rezono/test/test_rezono_1_requirements.py::test_rezono_1_requirement_parsing_and_diagnostics` | `rezono 1` reader parses `require` declarations (single/multi-clause, `when`, `over`, kind and relation targets, `at least`/`at most`/`exactly`, `invariant`, `means`/`@`) into `rezono.module/5`, round-trips losslessly, preserves ordinary `require` checks without collision, and rejects malformed syntax (`R000`). |
| 2. Lowering to `rezono.rules/2` | `compiler/tests/rezono/test_language_requirements.py::test_lower_requirement_to_rules_ir` | Compiler lowers `rezono 1` `require` declarations directly to `rezono.rules/2` (`<name>` functional outcome + `<name>_violation` derived finding, `invariant` flag, `means`/`@` bundle metadata, Feldera co-located view, `functional_open_domain` refusal for open domains, no silent drop, no `.dl` fallback). |
| 3. Witness of missing pattern | `compiler/tests/rezono/test_language_requirements.py::test_requirement_violation_witness_cites_trigger_and_missing_pattern` | Evaluating a pack emits a finding in `<name>_violation` when triggered and missing whose independent-checker-verified proof cites both the triggering pattern and what is missing; satisfied instances emit zero findings; untriggered instances yield `not_applicable no_match`; missing trigger slots yield `unknown no_value`; conflicting inputs yield `invalid multiple_values`. |
| 4. `unknown` without complete sweep | `compiler/tests/rezono/test_language_requirements.py::test_requirement_unknown_without_complete_sweep` | An observed `world open, complete by <cov>` target yields `unknown incomplete_read` (never false pass, never false violation) when `<cov>` does not hold and no witness is observed, yields `known true` when a witness is positively observed, and yields `known false` + finding whose verified witness cites `<cov>` once `<cov>` holds; plain `world open` yields `unknown open_world`. |
| 5. Cardinality / counts | `compiler/tests/rezono/test_language_requirements.py::test_requirement_cardinality_bounds_and_incomplete_sweep` | `at least 3`, `at most 4`, and `exactly 1` fail with observed-count witnesses when out of bounds under complete sweep/closed world, pass with zero findings when in bounds, yield `unknown incomplete_read` when unproven under incomplete sweep, and yield `not_applicable no_match` when untriggered. |
| 6. Proven bounds vs exact counts | `compiler/tests/rezono/test_language_requirements.py::test_requirement_proven_bounds_vs_exact_count` | On an incomplete `world open` register without conflict: `1` certain match proves both `exists` and `at least 1` (`known true`), `3` distinct confirmed replicas prove `at least 3` (`known true`), `5` distinct confirmed replicas prove violation of `at most 4` (`known false`), `>= 2` prove violation of `exactly 1` (`known false`), and `2` for `at least 3` (or `<= 4` for `at most 4`, `1` for `exactly 1`) remains `unknown incomplete_read`; checker-verified witnesses carry distinct identities, scope, and time, with coverage `<cov>` present only when exact counting is load-bearing. |
| 7. Conflicting & possibly-duplicate identities | `compiler/tests/rezono/test_language_requirements.py::test_requirement_bound_identity_conflict_and_alias_deduplication` | Conflicting identity claims yield `invalid multiple_values` (never silently dropped or masked even when 3 other clean replicas exist); duplicate/alias observations resolving to the same canonical identity are not double-counted toward `at least 3` (`unknown incomplete_read` on incomplete register); uncanonicalized / unproven-distinct records are not counted as extra distinct witnesses (`unknown no_match`, never `known true` or false `known false`). |

---

## Considered

- **Reusing bare `check` / `require <name>: <expr>` with `.any(...)` and `.count(...)` only.** Rejected: a bare Boolean check collapses "which `exists` clause failed", "what target kind/relation was missing", and "what observed count violated which bound" into an opaque expression, loses the structured `(k..., clause, target, bound, observed)` finding relation, and cannot directly drive future additive chase repair.
- **Adding `exists`, `least`, `most`, and `exactly` to the global hard keyword list.** Rejected: breaks ordinary domain identifiers and violates [`decisions/language-contextual-keywords.md`](language-contextual-keywords.md); block-scoping them inside `RequirementClauseLine` keeps all 16 expression keywords unchanged.
- **Allowing `require` over an `open` trigger kind without `over`.** Rejected: totalizing a four-state outcome relation over an open domain contradicts Feldera rule 2 and [`decisions/language-rezono-1.md`](language-rezono-1.md) §2; an explicit closed `over <domain>(...)` relation keeps the trigger domain finite and closed.
- **Requiring a complete sweep for all explicit cardinality bounds (conflating proven bounds with exact counts).** Rejected: observing `N` provably distinct, conflict-free matches monotonically proves `at least N` (and observing `N + 1` monotonically falsifies `at most N` and `exactly N`) regardless of unseen rows; conflating proven bounds with exact counts created an unsound discrepancy between `exists` and `at least 1` and hid real upper-bound violations (`5` replicas for `at most 4`) until a sweep closed.
- **Emitting a deficit violation or claiming satisfaction of an upper/exact bound when an observed target lacks a complete sweep.** Rejected: violates "unknown is explicit" and [`decisions/language-rezono-1-defaults.md`](language-rezono-1-defaults.md) §2; unproven bounds (`< N` for `at least N`, `<= N` for `at most N` / `exactly N`) MUST yield `unknown incomplete_read` (or `unknown open_world`) with zero violation rows.
- **Making every `require` block publication unconditionally (`invariant: true`).** Rejected: operational and audit obligations (CMDB drift, backup freshness, norm standing) must publish their witnessed findings rather than halting the entire epoch; opting into `invariant` on the header keeps blocking explicit where intended.
