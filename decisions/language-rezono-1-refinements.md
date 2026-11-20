---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-rezono-1-refinements
---

# Rezono 1 refinements: explicit bindings, `otherwise`, set-only collections, and deterministic arithmetic

This follow-up decision refines [the first-release decision](language-rezono-1.md) and [aggregate spelling and four-state folding](language-rezono-1-aggregate-spelling.md) on three fronts that must be settled before `rezono.rules/2` lowering and pack rule conversion proceed:

1. **No implicit existential variables in `rezono 1`:** relation calls never introduce undeclared variables; bare names in typed kind or enum positions are unambiguously element IDs or enum values, and multi-column existential joins use the tuple-set method form with an optional explicit binder (`Kind.any(x: ...)`, `rel.any(row: ...)`).
2. **Conflict-safe fallback on `n/a` with `otherwise`:** `a otherwise b` falls back to `b` only when `a` is `n/a`, preserving `known`, `unknown`, and `invalid` (with their witnesses) unchanged; an `unless` clause testing `x is known` where `x` can be `invalid` receives warning **`W115`**.
3. **Cross-engine expression parity:** `.count(pred)` matches `.where(pred).count()` everywhere, `x in S` includes `S` in `worst` when `x` is not `known`, every collection in `rezono 1` is strictly a **set** (refusing silent multiset path projection over collections with `R028` and adding `.one(expr)`), `round` uses an explicit target type or declared dimension default rather than alphabetical type lookup, all four rounding modes (`half_even`, `half_up`, `down`, `up`) stand beside distinct `floor` and `ceil` across every engine, and `rezono 1` adopts one symmetric 64-bit exact-number bound (`BOUND = 2^63 - 1`).

Nothing in this decision changes the syntax, printed form, or published semantics of `rezono 0` (`rezono.module/1`–`/4`, `rezono.rules/1`, `rezono.calc/1`), preserving [language reference §4b](../docs/rezono/v0.md#4b-language-version-and-deprecation).

---

## 1. No implicit existential variables in `rezono 1`

### Problem

Compilation in Rezono happens without facts: element IDs (such as `identity` of kind `Function`) are not listed in the schema. In [the first-release proposal](../docs/rezono/first-release-proposal.md), two platform derivations used incompatible bare-name rules side by side:

- `asks(s, identity) or provides(s, identity, _)`, where `identity` is an element ID of kind `Function`;
- `crossing(a, b, za, zb, _) and za.outside = yes and zb.entry_boundary = no`, where `za` and `zb` were undeclared existential variables of kind `Zone`.

Because element IDs are absent from the schema, no parser or typechecker can tell `asks(s, identity)` apart from an implicit existential variable `asks(s, fn)`. Auto-binding undeclared names in relation calls would silently turn `asks(s, identity)` into `asks(s, _)`, matching every function instead of `identity`.

### Decision

1. **A relation call never binds a new variable in `rezono 1`.** Every argument of a positional relation call `r(t1, ..., tn)` in a `rezono 1` `derived` body, `unless` guard, `check`/`warn`/`require`, or `ask` must be one of:
   - a variable already in scope (a derivation key parameter, an `extend s: K` subject binder, an explicit method binder, or `it`), or a path rooted at one;
   - a literal or typed ID (`Function:` `` `identity` ``);
   - the wildcard `_` in a positional membership test (preserving the symbolic token `_` per [language-rezono-1.md](language-rezono-1.md#1-fixed-invariants-and-scope));
   - an unbound bare name in a parameter position whose declared type is a **`Kind`** or an **`Enum`**, which resolves **unambiguously as an element ID of that `Kind` or a value of that `Enum`**, identical to `ask` name resolution ([`docs/rezono/expressions.md`](../docs/rezono/expressions.md#5-name-resolution) §3 and §5).
2. **Undeclared bare names outside kind or enum positions are `R001`.** Any unbound bare name that appears as the receiver of a path (`za.outside`), in a non-kind/non-enum argument position (such as an `Int` port column `crossing(a, b, z1, z2, port_var)`), or where no kind or enum type is expected fails typechecking with **`R001` (`unknown name`)** at that name's span.
3. **Existential joins over extra columns use the tuple-set method form.** Authors filter and quantify over a relation's named columns with `.where(...)` and `.any(...)` (or `Kind.any(...)`), already adopted by [the first-release decision](language-rezono-1.md) and [aggregate spelling](language-rezono-1-aggregate-spelling.md):
   - `rel.where(col1 = a and col2 = b).any(pred)`
   - `Kind.any(pred)`
4. **Optional explicit binder on method-form quantifiers, filters, and aggregates:**
   - Syntax: `S.any(x: pred)`, `S.all(x: pred)`, `S.none(x: pred)`, `S.where(x: pred)`, `S.count(x: pred)`, `S.sum(x: expr)`, `S.min(x: expr)`, `S.max(x: expr)`, and `S.one(x: expr)`.
   - Inside the parentheses, `<name> ":"` binds `<name>` to the current element or tuple of `S` in place of the implicit `it`. This eliminates `it` collisions in nested quantifiers and self-joins (for example, `Edge.any(e1: Edge.any(e2: e1.dst = e2.src))` or `crossing.any(row: row.src = a and row.dst = b and row.za.outside = yes)`).
   - Bare column or slot names of the element stay in scope when unambiguous; colliding with an outer variable still raises `R011` and is resolved by qualifying with the explicit binder (`row.za`). Re-binding a name already bound in an enclosing scope is refused with `R011` at the duplicate binder.
   - **JSON form (`rezono.module/5` and `rezono/src/tree.ts`):**
     - When omitted (implicit `it`), existing shapes stay unchanged: `{"agg": [op, base, expr]}` and `{"filter": [base, pred]}`.
     - When present, the explicit binder name is the final string element: `{"agg": [op, base, expr, binder]}` and `{"filter": [base, pred, binder]}`.
     - The canonical printer (`rezono/src/print-expression.ts`) writes `S.any(x: ...)` / `S.where(x: ...)` when `binder` is present and omits the prefix when absent.

### Rewritten platform derivations (`examples/platform/rules/core.dl`)

With this rule, `Service.authenticates` keeps its natural element-ID spelling while `outside_reaches_inside` and `recovery_reached` use the tuple-set form with zero undeclared variables:

```rezono
extend s: Service
  derived authenticates: Bool
    = asks(s, identity) or provides(s, identity, _)

derived outside_reaches_inside(a: Service, b: Service): Bool
  = crossing.where(src = a and dst = b).any(za.outside = yes and zb.entry_boundary = no)

derived recovery_reached(a: Service, b: Service): Bool
  = crossing.where(src = a and dst = b).any(zb.isolated_recovery = yes)
```

In `asks(s, identity)`, `identity` sits in the `Function`-typed second argument of `asks` and resolves directly to `Function:` `` `identity` ``. In `outside_reaches_inside` and `recovery_reached`, `src`, `dst`, `za`, and `zb` are declared columns of `crossing(src: Service, dst: Service, za: Zone, zb: Zone, port: Int)`, so the compiler synthesizes fresh IR variables from the relation signature when lowering to `rezono.rules/2`.

---

## 2. Conflict-safe fallback on `n/a` with `otherwise` and warning `W115`

### Problem

In [the first-release decision](language-rezono-1.md#2-one-derivation-form-derived) §2, an optional override had to be written as:

```rezono
derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = Service.where(provides(it, f, _)).one()
  unless not (chosen(a, f) is n/a) then chosen(a, f)
```

Writing `unless chosen(a, f) is known then chosen(a, f)` instead is a silent correctness bug: when two conflicting `Choice` rows make `chosen(a, f)` evaluate to `invalid multiple_values`, `chosen(a, f) is known` is `false`, so the `unless` clause does not fire and `needs` silently falls back to the default provider, hiding the conflict. Conversely, the double negation `not (chosen(a, f) is n/a)` repeats `chosen(a, f)` twice and proved opaque to a cold reader ([`first-release-proposal.md`](../docs/rezono/first-release-proposal.md#12-cold-read-check) §12).

### Decision

1. **Add the binary expression operator `a otherwise b` in `rezono 1` (and in `ask` expressions):**
   - **Exact four-state semantics:**

     | State of `a` | Result of `a otherwise b` | Witness and cause |
     | --- | --- | --- |
     | `known(v)` | `known(v)` | Witness of `a` (`b` is not required). |
     | `not_applicable` (`n/a`) | `b` (exact value, state, reason, cause) | Witness proving `a` is `n/a` **and** witness of `b`. |
     | `unknown(r)` | `unknown(r)` | Reason, cause, and witness of `a` (never falls back to `b`, preserving the two-world rule and explicit unknowns). |
     | `invalid(r)` | `invalid(r)` | Reason, cause, and witness of `a`, including every competing candidate (never masks conflicts). |

   - **Why only `n/a` falls back:** `n/a` means "this optional source does not apply here" (absent optional slot, empty `.one()` on `T?`, empty `.min`/`.max`). `unknown` means "incomplete knowledge" (open world, partial read, missing required input); falling back on `unknown` would fabricate a value from withheld or missing data. `invalid` means a contradiction or conflict; falling back on `invalid` would swallow it silently.
   - **Precedence, associativity, and keyword status:**
     - `otherwise` is an expression keyword in `rezono 1` (and `ask`); no existing pack in `examples/`, `packs/`, `run/`, or `build/` uses `otherwise` as a name. `rezono 0` modules are unaffected.
     - Grammar placement: `Otherwise = Imply otherwise Expr | Imply` (with `Expr = Cond | Otherwise`), right-associative and semantically associative (`(a otherwise b) otherwise c` equals `a otherwise (b otherwise c)` across all four states). It binds looser than `=>`, `or`, `and`, comparisons, and arithmetic (`a + b otherwise 0` parses as `(a + b) otherwise 0`; inside arithmetic or comparisons, parenthesize `(a otherwise b) + c`), and allows a conditional on the right (`a otherwise when c then b else d`).
   - **Typing:** `a` and `b` must have compatible types under `meet(a, b)` (`R003` on mismatch; `R005` if one is a set and the other a scalar). Result states are `(states(a) \ {not_applicable}) ∪ states(b)` when `not_applicable ∈ states(a)`, and `states(a)` otherwise. Static read analysis collects reads from both `a` and `b`; runtime evaluation short-circuits `b` when `a` is not `not_applicable`.
   - **JSON form (`rezono.module/5` and `rezono/src/tree.ts`):** `{"otherwise": [a, b]}`.
2. **Clear division of roles between `otherwise` and `unless`:**
   - **`otherwise`** expresses fallback from an optional value or optional derivation (`T?`, `.one()`, `.min`/`.max`) when it is `n/a`.
   - **`unless`** remains for policy and statutory exceptions that carry conditions, `@ source#locator` citations, and sibling conflict detection (`exception_conflict`).
3. **Warning `W115` on `unless` guards that can mask `invalid`:**
   - (`W113` is assigned to required fact origins in [fact-origin-required.md](fact-origin-required.md); `W114` is reserved for redundant `world closed` defaults in `rezono 1`.)
   - In `rezono 1`, whenever an `unless <cond> then <body>` clause tests `<expr> is known` (either as the entire `<cond>` or as a top-level conjunct of `<cond>`), AND static state typing shows `invalid ∈ states(<expr>)` (for example, `<expr>` reads a `.one()` derivation such as `chosen(a, f)` or `s.pin`, or a division), AND no sibling `unless` clause in the same derivation explicitly handles `<expr> is invalid`, the checker emits warning **`W115`** at the span of `<expr> is known`.
   - **`W115` message and hint:**
     - Message (`rezono/messages/en.json`): `` "`{0} is known` in `unless` skips `invalid` values of `{0}`" `` (with matching Dutch entry in `rezono/messages/nl.json`).
     - Hint (`hint.use_instead`): suggests `otherwise` when `<body>` is `<expr>` (e.g., `use \`chosen(a, f) otherwise ...\` instead`), or `not (<expr> is n/a)` when `<body>` computes a different expression.
   - **Counter-cases (no `W115`):**
     - `a otherwise b` emits no `W115`.
     - `unless not (x is n/a) then x` emits no `W115` (it already forwards `invalid` and `unknown`).
     - `unless x is known then ...` where `invalid ∉ states(x)` (for example, a closed slot whose states are `["known", "unknown"]` or `["known", "not_applicable"]`) emits no `W115`.
     - `unless x is known then ...` when another `unless` clause in the same derivation explicitly handles `x is invalid` emits no `W115`.

### Platform derivations rewritten with `otherwise` (cold-read target)

Combining Section 2 (`otherwise`) with Section 3.3 (`.one(expr)` instead of multiset path projection), the two platform overrides read directly from left to right:

```rezono
derived chosen(a: Service, f: Function): Service?
  over asks(a, f)
  = Choice.where(service = a and function = f).one(provider)

derived needs(a: Service, f: Function): Service
  over asks(a, f)
  = chosen(a, f) otherwise Service.where(provides(it, f, _)).one()
```

```rezono
extend s: Service
  derived pin: Release?
    = Pin.where(service = s).one(release)

  derived runs: Release
    = pin otherwise Release.where(
        it.product = s.product and stable = yes and released_on_day = s.product.newest_day
      ).one()
```

Before merge, an independent cold reader unfamiliar with Rezono reads both derivations and states in one sentence what each means, verifying that the choice/pin clearly takes precedence and that a conflict in the choice/pin is not silently swallowed.

---

## 3. Semantic parity: `.count(pred)`, `x in S`, Set-only collections, and deterministic `round`

### 3.1 `.count(pred)` equals `.where(pred).count()` everywhere

[Aggregate spelling](language-rezono-1-aggregate-spelling.md#the-three-positional-aggregates-of-the-native-rules) establishes that `S.count(pred)` is `S.where(pred).count()` and lowers to the same IR. Today `rezono/src/evaluate.ts` contradicts that equivalence: `S.count(pred)` runs `strict` over predicate results so a single member where `pred` evaluates to `n/a` turns the whole count into `n/a`, whereas `S.where(pred).count()` excludes `n/a` members in `filter` and keeps only `unknown` and `invalid` as undecided memberships.

**Decision:**

- **`S.count(pred)` is identically equal to `S.where(pred).count()` across TS (`rezono/src/evaluate.ts`), DuckDB, Feldera, Soufflé, and the independent checker.**
- For each member `m` of a known set `S`, evaluate `c = pred(m)` (combined with `m.maybe` via `and([m.maybe, c])` when `m` has uncertain membership):
  - `true` contributes `1`;
  - `false` and `n/a` are excluded (contribute `0` and do **not** turn the count into `n/a`);
  - `unknown` and `invalid` make the count undecided (`unknown` or `invalid`, taking the highest state and Appendix A.4 reason/cause).
- **Zero-argument `S.count()` is unchanged:** `S.count()` (with no predicate) counts the members of `S` directly and remains strict in member states under Appendix A.3 (`[known 1, n/a].count() = n/a` in `rezono 1`). The distinction matches Appendix A.5: in `S.count(pred)`, `pred` is a filter decision point (`T` selects, `F`/`N` omit, `U`/`I` undecided), whereas in `S.count()`, `n/a` is a member value itself.
- [Shared expression semantics](language-expression-semantics.md#1-expressions-and-evidence) §1 ("Filtered aggregate") is updated in lockstep to state this exact equivalence.

### 3.2 `x in S` includes `S` in `worst` when `x` is not `known`

Today `rezono/src/evaluate.ts` handles `a in lo..hi` strictly over `[x, lo, hi]`, so `n/a in 1..(invalid bad)` yields `invalid bad`, but `x in S` returns `x` immediately when `x.s !== 'known'` without inspecting `S`, so `n/a in [invalid bad]` wrongly yields `n/a` in violation of [`docs/rezono/expressions.md`](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) Appendix A.3 (`N < U < I`).

**Decision:**

- In `x in S` (for a known collection `S`), when `x` is not `known` (`n/a`, `unknown`, or `invalid`), evaluate `S`'s member states and uncertain memberships and return:
  `worst([x, ...all non-known members of S, ...all uncertain memberships m.maybe in S])`
  using Appendix A.3 state order (`N < U < I`) and Appendix A.4 tie-breaking (UTF-8 least reason code, then least cause).
- Concrete outcomes:
  - `n/a in [known a, invalid bad]` -> `invalid bad`
  - `n/a in [known a, unknown miss]` -> `unknown miss`
  - `unknown u1 in [invalid bad]` -> `invalid bad`
  - `n/a in (K where bad_filter)` (where `bad_filter` yields `invalid bad_filter` on a member) -> `invalid bad_filter`
  - `n/a in [known a, known b]` -> `n/a`
  - `n/a in []` (including an empty open kind such as `Team` with no rows) -> `n/a` (preserving existing open-kind behavior where `x` is `n/a` and `S` carries no higher state)
  - `known a in [known a, invalid bad]` -> `true` (decisive `or` match: `T or I = T`, matching Appendix A.1).
- When `S` itself is in a non-known state (`of.s !== 'known'`), `worst([x, of])` continues to apply.

### 3.3 Set vs. Bag: every collection in `rezono 1` is strictly a set (no silent multiset path projection)

Today `rezono/src/evaluate.ts` implements path hops over a collection (`clusters.spec.nodes`, `Plan.provider`) by pushing every fan-out item into an array without deduplication — silently producing a **multiset (bag)** — while `Kind`, relations, `T*` derivations, and `table collect` are **sets** (no duplicates), with no type distinction between sets and bags. This makes `Plan.provider.count()` return `3` when only `2` distinct providers exist, while deduplicating `clusters.spec.nodes` would silently drop contributions in `clusters.spec.nodes.sum()`.

**Decision (one clear choice: set-only collections in `rezono 1`, no bags):**

1. **Every collection in `rezono 1` is a set.** There is no bag/multiset type in `rezono 1`.
2. **Projecting a slot through a collection (`S.slot` where `S` has `set = true`) is refused in `rezono 1` with `R028` and `hint.use_instead`.**
   - Traversing a slot from a **single element** (`s.role.zone`, `s.product.newest_day`, or one hop from a scalar to a set such as `h.clusters`) is completely valid because the receiver is a scalar (`set = false`).
   - Applying `.slot` to a receiver that is already a collection (`set = true`, such as a `Kind`, relation tuple set, `.where(...)` result, or `T*` slot/derivation like `h.clusters`) is refused with **`R028`** at the collection-projection expression, with `hint.use_instead` pointing to the explicit row-oriented form:

     | Refused in `rezono 1` (`R028`) | Hint (`hint.use_instead`) | Semantics |
     | --- | --- | --- |
     | `S.p.sum()` (e.g. `clusters.spec.nodes.sum()`) | `S.sum(p)` (`clusters.sum(spec.nodes)`) | One contribution per row of `S` ([aggregate spelling](language-rezono-1-aggregate-spelling.md#rows-not-values)). |
     | `S.p.min()` / `S.p.max()` | `S.min(p)` / `S.max(p)` | Minimum / maximum of `p` over rows of `S`. |
     | `S.p.one()` (e.g. `Choice.where(...).provider.one()`) | `S.one(p)` (`Choice.where(...).one(provider)`) | Unique distinct value of `p` across rows of `S`. |
     | `S.p.count()` (e.g. `Plan.provider.count()`) | `S.count()` | Row count of `S` (for distinct targets, write `Provider.count(p: Plan.any(provider = p))`). |
     | `x in S.p` | `S.any(p = x)` | Membership without constructing a hidden bag. |
     | `S.p.any(q)` / `.all(q)` / `.none(q)` | `S.any(p.q)` / `.all(p.q)` / `.none(p.q)` | Quantification directly over rows of `S`. |

3. **`.one([expr])` accepts an optional projection expression `expr`:**
   - `S.one()` (no argument) yields the unique distinct element of closed set `S` (`Service.where(provides(it, f, _)).one()`).
   - `S.one(expr)` (and `S.one(x: expr)`) evaluates `expr` for each row of closed set `S` (strict in row membership and member states under Appendix A.3) and inspects the set of **distinct** known values `V`:
     - `|V| = 0`: `unknown no_match` (when declared type is `T`) or `not_applicable no_match` (when declared type is `T?`);
     - `|V| = 1`: `known(v)` with witness (`count` and `contributors_sha256`);
     - `|V| > 1`: `invalid multiple_values` carrying every distinct competing value and its supporting row(s) as conflict witness.
   - `rezono/src/parse.ts` lifts its current zero-argument restriction on `.one(...)` so both `S.one()` and `S.one(expr)` (and `S.one(x: expr)`) parse, typecheck, and print cleanly.
4. **Where checked:** because distinguishing a scalar receiver (`s.role.zone`) from a collection receiver (`h.clusters.spec.nodes`) depends on the schema's slot cardinalities, `R028` on collection path projection is enforced by the schema-aware `rezono 1` checker (`checkModule` / `check` in `rezono 1` mode) and compiler lowering.
5. **`rezono 0` is unchanged:** `rezono 0` modules and `rezono 0` `ask` questions keep their existing collection-path behavior with no `R028` and no `W107`.

### 3.4 Deterministic `round`, four rounding modes plus `floor`/`ceil`, and unified 64-bit exact-number bounds

#### A. Eliminating alphabetical type selection (`evaluate.ts` and `answer-schema.ts`)

Today `rezono/src/evaluate.ts` and `rezono/src/answer-schema.ts` choose a type for a computed dimension (such as `hourly_price * 730 h`, dimension `money EUR`, where `ty.name` is `undefined`) by sorting `Object.keys(schema.types)` alphabetically and picking the first matching dimension. Adding an unrelated type `AaaMicroEur` (dimension `money EUR`, scale `6`) silently alters both `round(hourly_price * 730 h)` and the output schema hash of existing `ask` queries.

**Decision:**

1. **Never choose a type by alphabetical name order.** Remove `Object.keys(schema.types).sort().find(...)` from both `rezono/src/evaluate.ts` and `rezono/src/answer-schema.ts`.
2. **Explicit target type on `round` (`round(x as TargetType)` and `round(x as TargetType, mode)`):**
   - Syntax: `round(x as TargetType)` or `round(x as TargetType, mode)` (AST: `{"call": ["round", [{"as": [x, "TargetType"]}, ...]]}`, keeping `rezono 0`'s `round(x)` / `round(x, mode)` AST unchanged). `as <Type>` is accepted only as the target-type specifier on `round`, `floor`, and `ceil` — not as a general cast operator.
   - Typecheck: `TargetType` must be a declared numeric type (or `Integer`) with the **exact same dimension** as `x`; otherwise report **`R003`**. The result type is `TargetType` (`ty.name = TargetType`, `inexact = false`).
3. **Deterministic target-type resolution for `round(x)` / `round(x, mode)` (without `as TargetType`):**
   - If `x` already carries a named numeric type (`ty.name !== undefined`, e.g., `Euro`, `Cents`, `GiB`, or `memory / 3` preserving `GiB`): round to `ty.name`'s `(factor, scale)`.
   - Else if `x` is dimensionless (`dim = {}`, i.e., `Ratio`): round to integer (`factor = 1`, `scale = 0`, result type `Integer`).
   - Else if the schema explicitly declares a default type for that dimension in **`schema.default_units[dimText(ty.dim)]`** (authored in a module as `default unit Euro` or supplied in schema metadata): round to that declared type, completely invariant to any other types of the same dimension.
   - Else (a computed dimension with no `as TargetType` and no declared `default_units` entry): refuse at check time with **`R013`** and `hint.use_instead` suggesting `round(... as <Type>)`. Never pick alphabetically.
4. **Deterministic `outputSchema` in `rezono/src/answer-schema.ts`:**
   - For a shown numeric expression with `ty.name === undefined` and non-empty `ty.dim`: use `schema.default_units?.[dimText(ty.dim)]` when declared; otherwise synthesize the canonical anonymous quantity type `Q0`, `Q1`, ... (already built in `answer-schema.ts`), deriving each base dimension's `storage_unit` deterministically from the dimension's canonical storage unit (sorted/verified invariant across all types of that dimension, never dependent on object insertion order or alphabetical type names).
   - Adding `AaaMicroEur` to a schema therefore changes neither `round(hourly_price * 730 h as Euro, half_even)` nor the shown slot type or generated quantity type definition in `outputSchema` for `ask Plan where true show hourly_price * 730 h`.

#### B. Four rounding modes and exact distinction from `floor` and `ceil`

Across TS (`rezono/src/evaluate.ts`), DuckDB (`compiler/rezono_compiler/calc_sql.py`), Feldera (`udf/udf.rs`), and the independent checker (`checker/rezono_checker/calc.py`), all six exact integer-rounding operations have one shared normative definition on every reduced fraction `n / d` (`d > 0`):

| Surface syntax | IR operator (`rezono.rules/2`, `contracts/calc.yaml`) | SQL / Rust UDF | Rule | `3/2` | `5/2` | `1/4` | `-1/4` | `-1/2` | `-3/2` | `-5/2` |
| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `round(x, down)` | `round_down` | `rezono_round_down(n, d)` | Toward `0` (truncation) | `1` | `2` | `0` | `0` | `0` | `-1` | `-2` |
| `round(x, up)` | `round_up` | `rezono_round_up(n, d)` | Away from `0` | `2` | `3` | `1` | `-1` | `-1` | `-2` | `-3` |
| `round(x, half_up)` | `round_half_up` (legacy alias: `round`) | `rezono_round_half_up(n, d)` (alias: `rezono_round`) | Half away from `0` | `2` | `3` | `0` | `0` | `-1` | `-2` | `-3` |
| `round(x, half_even)` | `round_half_even` | `rezono_round_half_even(n, d)` | Half to even (banker's) | `2` | `2` | `0` | `0` | `0` | `-2` | `-2` |
| `floor(x)` | `floor` | `rezono_floor(n, d)` | Toward `−∞` | `1` | `2` | `0` | `-1` | `-1` | `-2` | `-3` |
| `ceil(x)` | `ceil` | `rezono_ceil(n, d)` | Toward `+∞` | `2` | `3` | `1` | `0` | `0` | `-1` | `-2` |

- `floor` (toward `−∞`) and `ceil` (toward `+∞`) stay strictly distinct from `round(..., down)` (toward `0`) and `round(..., up)` (away from `0`), which differ on every non-integer negative number (`-1/4`, `-1/2`, `-3/2`, `-5/2`).
- Following [`contracts/calc.yaml`](../contracts/calc.yaml) ("Another mode is another operator, never a flag"), each mode is a distinct IR operator (`round_down`, `round_up`, `round_half_up`, `round_half_even`, `floor`, `ceil`). Legacy `round` in `rezono.calc/1` stays an exact alias for `round_half_up`.
- Scaling for a target type `T` with unit factor `u` (in storage units) and decimal scale `k >= 0` (quantum `q = u / 10^k`): compute exact `s = (x * 10^k) / u`, apply the chosen integer-rounding operator `m = op(s)`, and return the exact reduced rational `(m * u) / 10^k` (checked against the 64-bit bound below).
- In `rezono/src/check.ts` and `evaluate.ts`, `floor(x)` and `ceil(x)` (and `floor(x as TargetType)`, `ceil(x as TargetType)`) are checked and evaluated alongside `round(...)` using the exact same target-type rules.

#### C. Unified symmetric 64-bit exact-number bound (`BOUND = 2^63 - 1`)

Today `calc.py`, `calc_sql.py`, `checker/rezono_checker/calc.py`, and `udf/udf.rs` enforce the symmetric bound `BOUND = 2^63 - 1` (`[-(2^63 - 1), +(2^63 - 1)]`, rejecting `-2^63` in `calc_sql.py` as not fitting 64 bits), while `compiler/rezono_compiler/rules.py` and `rezono/src/native-rule-check.ts` allow `-2^63` in `rezono.rules/1` integers and `rezono/src/evaluate.ts` uses unbounded `BigInt` with no bound check at all.

**Decision:**

1. **One symmetric 64-bit exact-number bound for `rezono 1`:** across `rezono.rules/2`, `rezono.calc/1`, DuckDB, Feldera (`udf/udf.rs`), the independent checker, and the TypeScript evaluator (`rezono/src/evaluate.ts`), every `integer` value/constant and every reduced `rational` `n / d` (`d > 0`) MUST satisfy:
   `-(2^63 - 1) <= n <= +(2^63 - 1)` (`-9223372036854775807 .. 9223372036854775807`) and `1 <= d <= 2^63 - 1`.
2. **Why symmetric `[-(2^63 - 1), +(2^63 - 1)]`:** negation `-x`, absolute value `|n|`, sign normalization `d > 0`, and lifting an `integer` column to a `rational` `(v, 1)` in `rezono.rules/2` are all closed without signed 64-bit overflow on `i64`/`BIGINT`. Accepting `-2^63` in `integer` columns while rejecting `-2^63` in `rational` arithmetic creates a boundary contradiction inside `rezono.rules/2`.
3. **Compile-time vs runtime handling:**
   - **Compile-time / IR load (`rezono.rules/2`):** integer constants outside `[-(2^63 - 1), +(2^63 - 1)]` (including `-2^63 = -9223372036854775808` and `+2^63 = 9223372036854775808`) are rejected at IR validation.
   - **Runtime overflow (`rezono.rules/2` and `rezono/src/evaluate.ts`):** any arithmetic (`+`, `-`, `*`, `/`, unary `-`) or rounding step whose exact reduced result exceeds `BOUND` yields **`unknown`** with core reason code **`beyond_exact_bound`** (added to [`contracts/value.yaml`](../contracts/value.yaml) and `CORE_REASONS` for state `unknown`: the mathematical result exists, but exceeds the engine's exact 64-bit representation; `invalid` stays for undefined operations such as division by zero or schema contradictions).
   - **Backwards compatibility:** legacy `rezono.rules/1` (`rezono 0`) keeps `[-2^63, 2^63 - 1]` as documented in [`contracts/rules.yaml`](../contracts/rules.yaml) (preserving existing `rezono.rules/1` tests and [conformance-value-overflow.md](conformance-value-overflow.md)); legacy `rezono.calc/1` keeps its existing `beyond(op)` prose until `rezono.calc/1` retires. Both bounds (`rezono.rules/1` vs `rezono.rules/2`) are explicitly documented in [`contracts/rules.yaml`](../contracts/rules.yaml) and [`contracts/calc.yaml`](../contracts/calc.yaml).

---

## 4. IR, contract, SQL, and checker impact (for core review)

| Area | Change required | Effect on existing `rezono 0` / views |
| --- | --- | --- |
| [`contracts/rezono-module.yaml`](../contracts/rezono-module.yaml) (`rezono.module/5`) | Add `{"otherwise": [a, b]}` expression node; optional 4th `binder` string on `agg` and optional 3rd `binder` string on `filter`; optional projection argument on `one`; `{"as": [expr, type]}` target-type argument on `round`/`floor`/`ceil`; optional `default_units` schema mapping. | None on `rezono.module/1`–`/4`. |
| [`contracts/rules.yaml`](../contracts/rules.yaml) (`rezono.rules/2`) | Add `otherwise` binary operator on functional expressions; add `round_down`, `round_up`, `round_half_up`, `round_half_even` alongside `floor` and `ceil`; document symmetric `[-(2^63 - 1), +(2^63 - 1)]` exact-number bound for `rezono.rules/2` (beside legacy `[-2^63, 2^63 - 1]` for `rezono.rules/1`). | None on `rezono.rules/1`. |
| [`contracts/calc.yaml`](../contracts/calc.yaml) & [`contracts/value.yaml`](../contracts/value.yaml) | Add `round_down`, `round_up`, `round_half_up`, `round_half_even` to `Operator` enum (keeping `round` as alias for `round_half_up`); add core reason code `beyond_exact_bound` (allowed state: `unknown`). | Additive only. |
| DuckDB & Feldera SQL (`calc_sql.py`, `rules_sql.py`, `udf/udf.rs`) | Lower `a otherwise b` inside the same co-located functional view via `CASE WHEN a_state = 'not_applicable' THEN b_* ELSE a_* END` (**0 extra views**); add `rezono_round_down`, `rezono_round_up`, `rezono_round_half_up`, `rezono_round_half_even` DuckDB `HUGEINT` macros and Rust `i128` UDFs in `udf/udf.rs` returning `(0, 0)` on `BOUND` overflow -> `unknown beyond_exact_bound`. | Zero extra views per functional derivation; existing `rezono_round`, `rezono_floor`, `rezono_ceil` unchanged. |
| Independent checker (`checker/rezono_checker/`) | Verify `otherwise` witnesses (`a != n/a` -> witness of `a`; `a == n/a` -> witness that `a` is `n/a` plus witness of `b`, keeping `a`'s inputs in `closure.py` so fallback cannot be forged by omission); add `round_down`, `round_up`, `round_half_up`, `round_half_even` to `calc.py` / `evaluate.py`; enforce symmetric `BOUND = 2^63 - 1` for `rezono.rules/2`. | No change to `rezono.rules/1` or `rezono.calc/1` verification. |
| Language reader & checker (`rezono/src/`) | Add `checkModule` (schema-aware `rezono 1` module checker) enforcing no implicit existentials (`R001`), `W115` on `unless x is known`, `R028` + hint on collection path projection, and `R013` on ambiguous `round`; update `grammar.ts`, `parse.ts`, `print-expression.ts`, `check.ts`, `evaluate.ts`, `answer-schema.ts`, `schema.ts`, and `messages/{en,nl}.json`. | `rezono 0` parsing, checking, and evaluation unchanged (except fixing `.count(pred)` and `x in S` bugs in `evaluate.ts` to match Appendix A). |

---

## 5. Tests

Language-track red `M3:` tests introduced with this decision (all under `rezono/test/`):

| Test file & function | Mark | What it holds |
| --- | --- | --- |
| `rezono/test/test_rezono_1_no_implicit_existentials.py`, `test_rezono_1_no_implicit_existentials_and_explicit_binder` | `M3` | `asks(s, identity)` resolves `identity` as `Function` element ID; rewritten `outside_reaches_inside`, `recovery_reached`, and explicit binders `Kind.any(x: ...)` / `rel.any(row: ...)` parse, round-trip, and check cleanly; undeclared `za`/`zb` in `crossing(a, b, za, zb, _) and za.outside = yes` and undeclared `port_var` in an `Int` position fail with `R001`. |
| `rezono/test/test_rezono_1_no_implicit_existentials.py`, `test_rezono_0_keeps_rule_existentials` | green guard | `rezono 0` native rules keep positional existential variables in `rezono.module/3` without diagnostics. |
| `rezono/test/test_rezono_1_otherwise.py`, `test_rezono_1_otherwise_syntax_and_w115` | `M3` | `needs` and `Service.runs` with `otherwise` and chained `a otherwise b otherwise c` parse as `rezono.module/5` and round-trip; `unless chosen(a, f) is known then chosen(a, f)` emits warning `W115` with `hint.use_instead` naming `otherwise`; `otherwise`, `unless not (x is n/a)`, and `unless` over a non-invalid slot emit no `W115`. |
| `rezono/test/test_rezono_1_otherwise.py`, `test_otherwise_four_state_evaluation` | `M3` | Evaluates `a otherwise b` across all four states of `a` (`known`, `n/a`, `unknown`, `invalid`) and checks `R003` on mismatched branch types in `rezono/src/evaluate.ts` and `check.ts`. |
| `rezono/test/test_rezono_1_count_in_parity.py`, `test_count_pred_matches_where_count_with_na_unknown_invalid` | `M3` | Proves `S.count(pred)` equals `S.where(pred).count()` when `pred` evaluates to `n/a`, `unknown`, or `invalid` (excluding `n/a`, keeping `unknown`/`invalid` undecided), while zero-arg `S.count()` stays strict on `n/a` members. |
| `rezono/test/test_rezono_1_count_in_parity.py`, `test_in_set_takes_worst_over_set_when_lhs_not_known` | `M3` | Proves `n/a in [invalid bad] = invalid bad`, `n/a in [unknown miss] = unknown miss`, `unknown u1 in [invalid bad] = invalid bad`, and undecided filter membership propagation, while preserving `n/a in [known] = n/a`, `n/a in OpenEmpty = n/a`, and decisive `known k in [known k, invalid bad] = true`. |
| `rezono/test/test_rezono_1_set_no_bag.py`, `test_rezono_1_refuses_collection_path_projection` | `M3` | Refuses `clusters.spec.nodes.sum()`, `clusters.spec.nodes.max()`, `Plan.provider.count()`, and `Choice.where(...).provider.one()` in `rezono 1` with `R028` and `hint.use_instead`, while accepting `clusters.sum(spec.nodes)`, `clusters.max(spec.nodes)`, `Plan.count()`, `Choice.where(...).one(provider)`, and single-element paths. |
| `rezono/test/test_rezono_1_set_no_bag.py`, `test_rezono_0_keeps_collection_path_projection` | green guard | `rezono 0` modules keep `(Host where roomy).owner.count()` cleanly without `R028` or `W107`. |
| `rezono/test/test_rezono_1_deterministic_round.py`, `test_round_is_invariant_to_alphabetical_types_and_requires_target` | `M3` | Adding `AaaMicroEur` leaves `round(hourly_price * 730 h as Euro, half_even)` and the shown slot type/definition in `outputSchema` for `show hourly_price * 730 h` unchanged; `round` on a computed dimension without `as TargetType` or `default_units` fails with `R013`; `default_units` selects deterministically; dimension mismatch fails with `R003`. |
| `rezono/test/test_rezono_1_deterministic_round.py`, `test_round_modes_floor_ceil_and_64bit_bound` | `M3` | Verifies all six rounding operators (`down`, `up`, `half_up`, `half_even`, `floor`, `ceil`) on positive and negative fractions and enforces symmetric `BOUND = 2^63 - 1` (`±9223372036854775807` known, `±2^63` -> `unknown beyond_exact_bound`). |

Core-track `M3:` tests for `rezono.rules/2` IR, DuckDB/Feldera SQL macros/UDFs, and independent checker verification of `otherwise`, the four `round_*` operators, and symmetric `BOUND = 2^63 - 1` follow under `compiler/tests/` and `checker/tests/` once core review of Section 4 completes.

---

## Considered

- **Auto-binding undeclared bare names in relation calls as existential variables.** Rejected: compilation has no fact table, so element IDs like `identity` in `asks(s, identity)` would silently turn into wildcards `_`.
- **Requiring typed ID syntax (`Function:` `` `identity` ``) for every element ID while keeping implicit existential variables.** Rejected: hurts domain readability on every reference to a named element (`identity`, `tls`, `recovery`) and diverges from `ask`, where bare IDs resolve from their expected kind.
- **Keeping `unless not (x is n/a) then x` without adding `otherwise`.** Rejected: forces double negation and expression duplication for the most common optional-override pattern, and misled an independent cold reader.
- **Making `otherwise` also fall back on `unknown`.** Rejected: violates "unknown is explicit" and the two-world rule; a role reading `Choice` or `Pin` in part would silently receive the unchosen fallback instead of `unknown not_read_in_full`.
- **Using warning code `W114` for `unless x is known`.** Rejected: `W114` is reserved for redundant `world closed` in `rezono 1`; `W115` avoids collision.
- **Introducing an explicit `Bag<T>` type beside `Set<T>` for collection path projections.** Rejected: doubles the collection type system and method matrix when `S.sum(path)`, `S.min(path)`, `S.max(path)`, `S.one(path)`, `S.count()`, and `S.any(path = x)` already express every row-level and distinct-value operation cleanly on sets alone.
- **Keeping alphabetical type lookup in `round` and `outputSchema` with a warning.** Rejected: a warning does not stop adding an unrelated type (`AaaMicroEur`) from silently changing published amounts and schema hashes.
- **Allowing `-2^63` as the lower bound of `rezono.rules/2` integers while keeping `±(2^63 - 1)` for rationals.** Rejected: breaks closure under negation (`-(-2^63)`) and creates a mismatch whenever a `rezono.rules/2` integer feeds rational arithmetic or rounding.
