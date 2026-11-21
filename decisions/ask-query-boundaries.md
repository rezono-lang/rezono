---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: ask-query-boundaries
---

# Boundaries of free `ask … where … show` queries over role publications

Rezono serves two classes of read-only queries at the gate: fixed explanation questions (`GET /<pack>/<manifest>/ask/<term>` in [the named question walker](../edge/gate/src/ask.ts)) and free expression questions (`POST /<pack>/<manifest>/ask` in [the local gate](../edge/gate/src/local.ts) and [the expression evaluator](../edge/gate/src/expr.ts)). Both the REPL and [the MCP server](../tools/mcp/src/server.ts) evaluate free `ask` expressions through that same role-scoped gate boundary ([expressions reference](../docs/rezono/expressions.md)).

Free `ask` questions already support single-binder filtering, four-valued logic, exact arithmetic, sub-set aggregates, and role-scoped visibility. Three ad-hoc query capabilities remain reserved or unserved: grouped aggregates (`group by`), combining relations from multiple imported packs in one question, and temporary read-only local rules defined during asking. This decision fixes what `ask … where … show` can and cannot do, defines the invariants that govern all free queries, and specifies the exact contract for those three capabilities.

## 1. What `ask … where … show` can and cannot do

| Capability | Status | Boundary |
| --- | --- | --- |
| Single-binder `ask [binder:] Kind where expr [show expr, …]` | Supported | Role-scoped pinned manifest (`m-N`), exact arithmetic, four-valued logic, deterministic key order, paged `rezono.answer/1`. |
| Grouped aggregates (`group by` with `count`, `sum`, `min`, `max`) | Planned (`extra:`) | Closed role-readable sets only; preserves four value states, role filter, and contributor witnesses (section 3). |
| Multi-binder joins across relations from multiple imported packs | Planned (`extra:`) | Joins kinds and derived relations declared by imported packs in the pinned bundle, under role filtering and published witnesses (section 4). |
| Request-scoped local rules evaluated during asking | Planned (`extra:`) | Strictly read-only, safe (range-restricted), stratified, step/row-bounded, role-scoped, and witnessed (section 5). |
| Mutations, writes, or proposals (`propose`, `+ …`, `- …`, write HTTP methods) | Permanently refused | `ask` has effect class `reads` ([expressions reference](../docs/rezono/expressions.md#8b-effect-classes)). Fact changes belong to [local suppositions](local-suppose.md) (`rezono-suppose`) or reviewed proposals. |
| Reading outside the authenticated role's view | Permanently refused | Unreadable kinds, slots, relations, rows, and witnesses are invisible (`R001` / 400); spoofed role parameters or headers are rejected or ignored. |
| Silent coercion of missing, `n/a`, `unknown`, or `invalid` values | Permanently refused | Missing values never become `0` or `false`; partial snapshots downgrade the effective world to `open` (`not_read_in_full`) and refuse closed-world aggregates (`R004`). |
| Unbounded computation, unsafe rules, or unstratified recursion | Permanently refused | Every `ask` runs under deterministic `budget.rows` and `budget.steps` (HTTP 422 `cut`, never a partial answer as complete); unsafe (`R042`) or unstratified (`R043`) local rules are refused before evaluation. |
| Non-determinism, external I/O, or unverified search | Permanently refused | No wall-clock reads, randomness, floating-point approximations, or network/filesystem side effects. Large non-enumerable search stays behind [solver proposals](solver-proposals.md). |

## 2. Shared invariants for all `ask` queries

Every current and extended form of `ask … where … show` enforces five non-negotiable rules:

1. **Role filter and the two-world rule:** Every query resolves names, checks types, reads snapshots, and attaches witnesses strictly against the authenticated role's view of the pinned manifest. Two manifests whose role views are equal produce byte-identical answers ([expressions reference](../docs/rezono/expressions.md#7a-visibility-and-the-two-world-rule)). A relation that the role reads only in part (`complete: false` and `full: false`) is treated as `open` for that role; missing scalar values carry `unknown` with reason `not_read_in_full`, never `n/a` (absent).
2. **Four value states (`known`, `not_applicable`, `unknown`, `invalid`):** Expressions, filters, group keys, join predicates, aggregates, and local rules follow Appendix A of the [expressions reference](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and [language reference](../docs/rezono/v0.md#7b-truth-and-value-states). At every decision point (`where`, group key, or filter), `true` keeps the row, `false` drops it, `n/a` drops it and increments `counts.not_applicable`, and `unknown` or `invalid` emits an `Undecided` row with its `state`, `reason`, and `cause`.
3. **Proof-backed witnesses:** Answers that aggregate groups, combine derived/imported relations, or derive tuples via local rules attach structured `witnesses` and `steps` in `rezono.answer/1` ([explain contract](../contracts/explain.yaml), [proof contract](../contracts/proof.yaml)). Every witness cites only rows and published witnesses readable by the authenticated role.
4. **Strict read-only execution:** `POST /<pack>/<manifest>/ask` writes zero bytes to the publication store and never modifies manifests, snapshots, packs, or heads.
5. **Deterministic bounded execution:** Row reads and evaluation steps are counted solely over the role's view against `budget.rows` and `budget.steps`. Exceeding either limit aborts evaluation cleanly with HTTP 422 (`{ "cut": { "budget": "rows" | "steps", "limit": N } }`) and returns no partial answer.

## 3. Grouped aggregates (`group by` with `count`, `sum`, `min`, `max`)

Lift `R015` on `group by` in `rezono/src/parse.ts` and support grouped checking, schema generation, and evaluation across `rezono/src/` and `edge/gate/src/`:

```rezono
ask e: Entry where e.active show e.bucket, count(), sum(e.weight), min(e.weight), max(e.weight) group by e.bucket
```

- **Row partitioning and four states:**
  - `where` is evaluated first per binder row: `false` is excluded, `n/a` increments `counts.not_applicable`, and `unknown`/`invalid` emits an `Undecided` row.
  - For rows passing `where`, each `group by` key expression is evaluated:
    - `known`: the row enters the group for that canonical key (groups are ordered in canonical UTF-8 key order).
    - `n/a` (absent): the row is excluded from all groups and increments `counts.not_applicable`; it is never placed in a synthetic null or empty group.
    - `unknown` or `invalid`: the row is emitted in `undecided` with its `state`, `reason`, and `cause` and is never grouped.
- **Aggregate semantics within each group (Appendix A.3):**
  - `count()`, `sum(expr)`, `min(expr)`, and `max(expr)` are closed-world aggregates: both the binder kind and every aggregated slot/relation must be `closed` and read in full by the role. If any of them is `open` or read only in part (`full: false, complete: false`), checking fails closed with `R004` (HTTP 400).
  - Within a closed group, `count()`, `sum`, `min`, and `max` are strict in their inputs:
    - All inputs `known` produce the exact `known` aggregate value.
    - Any `invalid` input yields `{ "$invalid": reason }` (`invalid` outranks `unknown` and `n/a`).
    - Any `unknown` input (with no `invalid`) yields `{ "$unknown": reason }` — never `0` and never silently skipped.
    - Any `n/a` input in `sum`, `min`, or `max` (with no `unknown`/`invalid`) propagates `{ "$na": reason }`; `count()` counts the rows in the group (independent of optional non-grouped slots).
- **Witnesses:** Each grouped `Answer` row has a corresponding `Witness` in `answer.witnesses` (recording `aggregates` with `group_key`, `count`, `contributors_sha256`, and canonical `result`) and `AnswerStep` entries in `answer.steps` with `how: "contributes"` (and `value` for `sum`, `min`, and `max`) linking the group conclusion to every role-readable contributing row.

## 4. Combining relations from multiple imported packs in one `ask`

A pack that imports multiple packs (`bundle.imports`) compiles their kinds, slots, and derived relations into one pinned `schema-bundle.json` and publishes role-filtered snapshots and witnesses for each relation the role may read. To combine relations from multiple imported packs in a single question:

```rezono
ask a: AlphaTag, b: BetaMetric where a.item = b.item show a.item, a.tag, b.tier
```

- **Multi-binder syntax and checking:** Lift `R015` on `MoreBinder` (`, name: Type`) in `rezono/src/parse.ts` and bind all declared binders in `rezono/src/check.ts`, `rezono/src/answer-schema.ts`, and `rezono/src/evaluate.ts`. Every binder must name a kind or derived relation present in the role's schema (`roleSchema`). Ambiguous bare slot names across binders are refused with `R011`, requiring explicit qualification (`a.slot`, `b.slot`).
- **Role filtering:**
  - If the role lacks read access to any binder's kind or relation (for example, it reads `pack_a`'s relation but not `pack_b`'s), checking fails closed with `R001` (HTTP 400) without leaking whether the unreadable relation exists.
  - When the role reads both relations, only tuples present in the role's snapshots are joined. Hidden rows from either imported pack never appear in `nodes`, `dataset`, `undecided`, `counts`, `witnesses`, or `steps`.
- **Witness linkage:** `POST /<pack>/<manifest>/ask` resolves published witnesses from the role's `manifest.witnesses` (and `fact_sources` for base rows) for every joined derived/base tuple and emits them in `answer.witnesses` and `answer.steps`, connecting each joined `Answer` row to its participating rows and published proofs from both imported packs.

## 5. Local read-only rules defined during asking

A caller may define temporary local rules for one `ask` request over the role's pinned publication, analogous in witness and isolation discipline to [local suppositions](local-suppose.md) (`rezono-suppose`), without writing anything to the store:

```json
{
  "rules": [
    "rule high_score(x: Item) when x in Item and x.score >= 50"
  ],
  "text": "ask x: Item where high_score(x) show x.score"
}
```

- **Request shape:** `POST /<pack>/<manifest>/ask` accepts an optional `rules` array of non-empty strings (each a single local rule declaration) alongside `text`. Local rules exist solely for the duration of that single request and are never persisted or shared across requests.
- **Checking, authorization, and safety (before any row is read):**
  - Every local rule is checked against the authenticated role's schema (`roleSchema`). Referencing any kind, slot, or relation not readable by the role is refused with `R001` (HTTP 400).
  - Any write, mutation, or proposal statement (`+ …`, `- …`, `propose …`, or non-rule command) inside `rules` is refused with HTTP 400.
  - Local `ask` rules follow the same positive `x in Kind` binding rule as [native rules](language-native-rules.md): every head variable must be bound by a positive premise (`x in Kind`; otherwise refused with `R042`, HTTP 400), and local rules must be stratified (no recursion through negation or aggregation, such as `rule bad(x: Item) when x in Item and not bad(x)`; otherwise refused with `R043`, HTTP 400).
- **Bounded evaluation, four states, and witnesses:**
  - Local rules evaluate strictly over the role's readable snapshots under the shared `budget.rows` and `budget.steps` limits. Exceeding either budget aborts with HTTP 422 (`cut`) and returns no partial answer.
  - Four value states propagate through local rule bodies and heads: a row whose body evaluates to `unknown` or `invalid` produces an `Undecided` row with its `state`, `reason`, and `cause` rather than silently disappearing.
  - The answer sets `computed: true` ([explain contract](../contracts/explain.yaml)) and attaches `witnesses` and `steps` naming the local rule (`rule_id`), variable `bindings`, and exact role-readable `premises` (plus underlying published witnesses when a local rule reads a published derived relation), while leaving the publication store byte-for-byte unchanged.

## 6. Considered alternatives

- **Allowing `ask` to accept inline fact mutations alongside local rules:** Rejected. Mixing fact mutation into `ask` violates its `reads` effect class and blurs the line with [local suppositions](local-suppose.md) (`rezono-suppose`, effect class `transacts`) and reviewed proposals (`writes`).
- **Coercing missing or `unknown` cells to `0` in grouped aggregates:** Rejected. Coercion violates four-valued semantics (`unknown` is never zero) and breaks the two-world rule when a role reads a relation in part.
- **Adding a separate cross-pack join endpoint instead of multi-binder `ask`:** Rejected. Imported packs already compile into one pinned schema bundle with unified role access; extending `ask` keeps one grammar, one question hash, one output schema contract, and one role boundary across the gate, REPL, and MCP.
- **Permitting unstratified or unbounded local rules with runtime timeouts:** Rejected. Wall-clock timeouts break determinism and the two-world rule; static stratification (`R043`), range restriction (`R042`), and deterministic `budget.rows`/`budget.steps` cuts keep answers reproducible.

## 7. Tests

All three missing capabilities are recorded as strict `extra:` red tests in [edge/gate/test/test_ask_query_boundaries.py](../edge/gate/test/test_ask_query_boundaries.py) (driven through [the local gate](../edge/gate/src/local.ts) and [the expression evaluator](../edge/gate/src/expr.ts)):

1. `test_ask_grouped_aggregates_four_states_witness_and_role_filter`: verifies `group by` with `count`, `sum`, `min`, and `max` across `known`, `n/a` (absent), `unknown`, and `invalid` groups, contributor witnesses, `not_applicable` handling of absent group keys, and counter-cases refusing aggregates over partial/open role snapshots (`R004`) and isolating a scoped role.
2. `test_ask_combines_relations_from_multiple_imported_packs_with_role_filter_and_witness`: verifies a multi-binder `ask` joining derived relations from two imported packs with published witnesses attached, plus counter-cases refusing a role that can read only one imported pack (`R001`) and isolating a narrow role from hidden joined rows and witnesses.
3. `test_ask_local_rule_is_read_only_bounded_authorized_and_witnessed`: verifies a request-scoped local rule evaluated over the role's publication with `computed: true`, four-valued `undecided` propagation, and rule/premise witnesses, plus counter-cases proving byte-for-byte store immutability, refusal of write attempts, refusal of unauthorized slots (`R001`), refusal of unstratified negation (`R043`), and deterministic `cut` when `budget.steps` is exceeded.
