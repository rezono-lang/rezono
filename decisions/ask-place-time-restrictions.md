---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: ask-place-time-restrictions
---

# Place, valid-time, and knowledge-time restrictions in `ask` (and v2 `show extent`)

Questions in Rezono (`POST /<pack>/<manifest>/ask` in [`edge/gate/src/local.ts`](../edge/gate/src/local.ts), evaluated via [`edge/gate/src/expr.ts`](../edge/gate/src/expr.ts) and [`rezono/src/parse.ts`](../rezono/src/parse.ts)) currently run over a single snapshot with no place, valid-time, or knowledge-time restriction:

- [`rezono/src/parse.ts`](../rezono/src/parse.ts) reports question contexts (`at`, `during`, `as known`) as `R015` and does not accept the `as known on <date>` spelling or a bare valid-time interval `during <from>..<until>`.
- [`edge/gate/src/expr.ts`](../edge/gate/src/expr.ts) neither reports the active scope/default restriction nor attaches published witnesses from the selected manifest to an `ask` answer.
- [`edge/gate/src/local.ts`](../edge/gate/src/local.ts) cannot restrict `POST /<pack>/<manifest>/ask` to an earlier knowledge cut (`as known on <date>`), a place (`at <place>`), or a validity period (`during <period>`).

This decision defines:

1. **Release 1 (`M3`):** three optional sheaf restrictions on `ask` — `at <place>`, `during <period>`, and `as known on <date>` — over the same pack model, role view, rules, and witnesses, restricting only the domain of evaluation;
2. **Explicit scope and witnesses:** every `ask` answer explicitly reports its active restriction (or default: current validity and everything known in `<manifest>`) and carries the published witnesses of the matched rows from the selected manifest;
3. **Four-valued discipline:** `during <period>` outside every validity period and `as known on <date>` before the first publication return `unknown` with an explicit reason code — never `false`;
4. **Release 2 (`later:`):** `show extent`, returning a constructive place × valid-time region decomposition where each piece carries one of the four epistemic states and an explicit reason ("not everywhere true" ≠ "somewhere false").

## 1. Sheaf-restriction principle

`at <place>`, `during <period>`, and `as known on <date>` do not define a second evaluation semantics or a separate query engine. They act as **sheaf restrictions** over the same model, the same role-scoped publication, and the same checked witnesses ([`edge/gate/src/ask.ts`](../edge/gate/src/ask.ts), [`contracts/proof.yaml`](../contracts/proof.yaml)):

- Restricting to a smaller place or valid-time domain never fabricates `false` where no fact or version covers the domain; absence of coverage yields `unknown` with an explicit reason code.
- Restricting to an earlier knowledge date reads the latest readable verified manifest at or before that date, enforcing [`stillReadable`](central-read-access.md) and withdrawal rules, and quotes that manifest's own witnesses.
- Without any restriction, `ask` evaluates at the requested manifest's current validity and full knowledge up to its `knowledge_time`, and reports that default scope explicitly.

## 2. Grammar and v0 conformance compatibility

In [`rezono/src/grammar.ts`](../rezono/src/grammar.ts), [`rezono/src/parse.ts`](../rezono/src/parse.ts), [`rezono/src/check.ts`](../rezono/src/check.ts), and [`rezono/src/print-expression.ts`](../rezono/src/print-expression.ts):

- **Question context clauses** stand between the asked kind and `where`:
  - `at <place>`: `at Atom` (identifier, text literal, or date/atom).
  - `during <period>`: `during Atom (rangeOp Atom)?`, accepting a half-open or closed date range (e.g. `2026-01-01..<2026-04-01`, `2026-01-01..2026-03-31`), a calendar year/month/date (`2026`, `2026-03`, `2026-03-15`), or a named period/stage identifier (`q1-2026`).
  - `as known on <date>`: accepts both `as known on Atom` and the existing v0 spelling `as known Atom`. Both populate `context.as_known`. Because `on` is already a contextual word (`grammar.ts`), matching `as known on Atom` before `as known Atom` preserves `on` as an ordinary identifier when no atom follows it.
  - Each context axis still appears at most once (`R018`).
- **Preserving v0 conformance cases (no deadlock):** The frozen v0 conformance suite ([`docs/rezono/expressions.md`](../docs/rezono/expressions.md) §1, cases `E35`, `E36`, `E39`, `E40` in `docs/rezono/cases/`) expects `R015` when `parse(text)` or `check(text, schema)` is called with no options, and expects `print()` to format `context.as_known` as `as known <atom>`. Therefore:
  - `parse(text)` and `check(text, schema)` without options keep emitting `R015` on question contexts and keep `print()` formatting `as known <atom>` (and `during <from><op><until>` for range operands, `during <atom>` otherwise).
  - `parse(text, { allowContext: true })` and `check(text, schema, { allowContext: true })` accept `at`, `during`, and `as known [on]` without `R015`. [`edge/gate/src/expr.ts`](../edge/gate/src/expr.ts) enables `{ allowContext: true }` when evaluating gate `ask` requests.
  - `normalQuestion` and `questionHash` retain the normalized `context` so questions with different restrictions produce distinct hashes.

## 3. Release 1 (`M3`): Gate `ask` restrictions, default scope, and witnesses

### 3.1 Explicit `restriction` object in `rezono.answer/1`

Every `POST /<pack>/<manifest>/ask` answer ([`contracts/explain.yaml`](../contracts/explain.yaml), [`edge/gate/src/expr.ts`](../edge/gate/src/expr.ts)) includes a `restriction` object reporting the active scope:

```json
{
  "default": true,
  "at": null,
  "during": null,
  "as_known": null,
  "resolved_manifest": "m-2",
  "knowledge_time": "2026-03-01T00:00:00Z"
}
```

- **Default (no restriction written):** `default` is `true`, `at`, `during`, and `as_known` are `null`, `resolved_manifest` is `<manifest>`, and `knowledge_time` is that manifest's `knowledge_time`.
- **Restricted:** `default` is `false`, each specified axis carries its normalized text (`at`, `during`, `as_known`) and omitted axes are `null`. `resolved_manifest` and `knowledge_time` name the manifest actually read (or `null` when `as known on <date>` precedes the earliest published epoch).

### 3.2 Witnesses on `ask` answers

For every matched row in `nodes` of a `POST /<pack>/<manifest>/ask` answer:

- The gate loads the selected manifest's verified role-scoped witness set (`manifest.witnesses` for the caller's role, and `manifest.fact_sources` when present) using the same verification rules as named questions ([`edge/gate/src/local.ts`](../edge/gate/src/local.ts)).
- The answer includes `witnesses` (`Witness[]`, and `calc_witnesses` when present) containing the complete published witness for each matched conclusion row on the page (in canonical page order), and attaches base-row `sources` on `nodes` when present.
- When a fact was corrected between epochs `m-1` and `m-2`, asking the same question without `as known on` and with `as known on <date between m-1 and m-2>` returns two distinct answers — each carrying the value and complete verified witness of its respective epoch.

### 3.3 Knowledge-time restriction: `as known on <date>`

Given `POST /<pack>/<manifest>/ask` with `as known on <date>` (or `as known <date>`):

1. The gate inspects published main epochs `m-1 .. <manifest>` in descending epoch order (never beyond `<manifest>`).
2. An epoch matches when its `knowledge_time` is on or before `<date>` (calendar-date comparison `knowledge_time.slice(0, 10) <= date` for `YYYY-MM-DD`, or exact UTC instant comparison for full timestamps).
3. For the latest matching epoch `m-k`:
   - Enforce withdrawals (`410 Gone`) and [`stillReadable(m-k, current)`](central-read-access.md) (`404` if revoked under current role authority).
   - Evaluate the `ask` (including any `at` / `during` clauses) over `m-k`'s verified snapshots, witnesses, and sources.
   - Report `manifest_id: "m-k"`, `restriction.resolved_manifest: "m-k"`, `restriction.knowledge_time: m-k.knowledge_time`, `restriction.as_known: "<date>"`, and `restriction.default: false`.
4. **Before first publication (counter-example):** If no epoch `m-1 .. <manifest>` has `knowledge_time <= <date>`:
   - Do **not** return `404`, `400`, or `false`.
   - Return `200 OK` (`rezono.answer/1`) with `restriction.resolved_manifest: null`, `restriction.knowledge_time: null`, `nodes: []`, `witnesses: []`, `counts.rows: 0`, `counts.undecided >= 1`, and `undecided` containing `state: "unknown"` with explicit reason `"before_first_known"` for every visible binder row of the asked kind (or a single `"*"` entry if the kind has no visible rows yet).

### 3.4 Place restriction: `at <place>`

A kind or derived relation participates in place restriction via a single-valued `place` slot/column (or an explicit `place_slot` declared in the bundle).

- Rows whose `place` equals `<place>` remain in the restricted domain and evaluate normally (returning matched rows with their witnesses, or `undecided` if the condition is `unknown`/`invalid`).
- Rows whose `place` is known to differ from `<place>` lie outside the restricted domain and are excluded from the restricted answer.
- Rows whose `place` is `unknown` (missing on an open or partial snapshot) cannot be known outside `<place>` and remain `undecided` (`state: "unknown"` with their missing-slot reason).
- Asking `at <place>` on a kind that declares no place slot/column is refused with `400`.

### 3.5 Valid-time restriction: `during <period>`

A kind or derived relation participates in valid-time restriction via half-open validity bounds `valid_from` (inclusive ISO date) and optional `valid_until` (exclusive ISO date, matching [dated facts](language-dated-facts.md) and [`packs/std-time`](bitemporal-staircase-reading.md)), or a `period` slot.

- A `<period>` expression normalizes to a half-open ISO date interval `[q_start, q_end)`:
  - `YYYY-MM-DD..<YYYY-MM-DD` → `[start, end)`
  - `YYYY-MM-DD..YYYY-MM-DD` → `[start, nextDay(end))`
  - `YYYY-MM` → `[YYYY-MM-01, nextMonth(YYYY-MM)-01)`
  - `YYYY` → `[YYYY-01-01, (YYYY+1)-01-01)`
  - `YYYY-MM-DD` → `[date, nextDay(date))`
- **Inside validity:** If a row's validity interval `[r_start, r_end)` covers `[q_start, q_end)` (`r_start <= q_start` and either `r_end` is absent or `q_end <= r_end`), the row is valid during `<period>` and evaluates normally — matching rows return `known` with their verified witnesses.
- **Outside every validity period (never `false`):** If `[q_start, q_end)` is not covered by a row's validity period (for example, `q_end <= r_start`, `r_end <= q_start`, or only partial overlap), the row's slots evaluate as `unknown no_version_applies` in that restricted domain — **never** `false` and never closed-world absent. Consequently:
  - Both positive conditions (`where entry = e-1`, `where amount = "100"`) and negated conditions (`where not (amount = "100")`) evaluate to `unknown`, yielding `nodes: []`, `counts.rows: 0`, `counts.undecided >= 1`, and `undecided` entries with `state: "unknown"` and `reason: "no_version_applies"`.
  - No `false` answer is ever synthesized for a period outside validity.

## 4. Release 2 (`later:`): `show extent` over place × valid time

In Release 2, `ask` adds `show extent` to ask *where and when* a predicate holds across the product **place × valid time**:

```rezono
ask Entry where status = "open" show extent
```

- **Grammar:** `show extent` is accepted as an alternative `Show` form (`extent` stays contextual, not a hard keyword).
- **Answer shape:** The `rezono.answer/1` response carries an `extent` object:

```json
{
  "axes": ["place", "valid"],
  "regions": [
    {
      "binder": "e-north",
      "place": "north",
      "valid": { "from": "2026-01-01", "until": "2026-07-01" },
      "state": "known",
      "holds": true,
      "reason": null
    },
    {
      "binder": "e-south",
      "place": "south",
      "valid": { "from": "2026-01-01", "until": "2026-07-01" },
      "state": "unknown",
      "holds": null,
      "reason": "not_read_in_full"
    }
  ],
  "everywhere_true": false,
  "somewhere_false": false
}
```

- **Four states per region:** Every region carries its `(place, valid)` piece, its epistemic `state` in `{"known", "unknown", "not_applicable", "invalid"}`, `holds` (`true` or `false` when `state == "known"`, otherwise `null`), and a non-empty `reason` whenever `state != "known"`.
- **Constructive logic ("not everywhere true" ≠ "somewhere false"):**
  - `everywhere_true` is `true` iff every region has `state == "known"` and `holds == true`.
  - `somewhere_false` is `true` iff at least one region has `state == "known"` and `holds == false`.
  - When a predicate is `known` (`holds: true`) in one place/period and `unknown` (with an explicit reason) in another, `everywhere_true` is `false` **and** `somewhere_false` is `false`: lack of knowledge in one region never collapses into falsity.

## 5. Considered alternatives

- **A separate `/ask-restricted` endpoint or query parameters beside `POST /ask`.** Splits one language concept into two surfaces and disconnects `ask` text/hashes from the restrictions that determined the answer.
- **Dropping `R015` unconditionally in `rezono/src/parse.ts`.** Breaks the frozen v0 conformance suite (`docs/rezono/cases/E35.yaml`, `E36.yaml`, `E39.yaml`, `E40.yaml`), which is protected evidence; gating context acceptance behind `{ allowContext: true }` (just as [`rezono/src/check.ts`](../rezono/src/check.ts) already gates `rezono 1` typing options) keeps v0 conformance intact while enabling full restriction evaluation in `edge/gate`.
- **Treating `during <period>` outside validity as an empty `known` row set (`false`).** Violates Rezono's explicit-unknown invariant: negating the condition (`not (...)`) would wrongly report rows as `true` for periods where no version exists.
- **Collapsing `show extent` into a boolean "holds everywhere" summary.** Loses per-region reasons and conflates "not everywhere true" with "somewhere false", breaking constructive four-valued semantics.

## 6. Red tests

Three strict red tests live in [`edge/gate/test/test_ask_place_time_restrictions.py`](../edge/gate/test/test_ask_place_time_restrictions.py) backed by the self-contained domain-free probe [`edge/gate/test/ask-place-time-probe.mts`](../edge/gate/test/ask-place-time-probe.mts):

1. `M3`: `test_ask_as_known_on_corrected_fact_returns_distinct_witnessed_answers` — verifies on a corrected fact across two epochs that (a) unrestricted `ask` reports default scope, the new value, and its complete witness; (b) the same `ask` with `as known on <earlier date>` reports the active restriction, the old value, and its distinct complete witness; (c) `at <place>` restricts the domain and preserves witnesses; and (d) counter-example: `as known on <before first publication>` returns `unknown` with explicit reason `"before_first_known"`, never `false`.
2. `M3`: `test_ask_during_outside_validity_returns_unknown_with_reason_not_false` — verifies that `ask ... during <period outside every validity>` returns `unknown` with explicit reason `"no_version_applies"` (never `false`, verified on both a positive condition and its negation `not (...)`), and counter-example: `during` within a valid period returns `known` with its verified witness.
3. `later`: `test_ask_show_extent_returns_place_time_regions_with_four_states` — verifies v2 `show extent` across place × valid time with all four epistemic states and per-region reasons, plus the constructive-logic counter-example where `known` (`true`) at one place and `unknown` at another reports `everywhere_true: false` and `somewhere_false: false` (never "somewhere false").
