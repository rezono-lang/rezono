---
decider: [language, core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: healthcare-allowance-three-sources
---

# Expand the healthcare allowance slice into three sources with derived benefit partnership

[The first slice of the healthcare allowance](language-healthcare-allowance-slice.md) kept one kind, `Household`, with stored Booleans `partner: Bool` and `insured: Bool` and a pre-summed `joint_income: Cents`. That proved inline parameter versions, ordered exceptions and dated facts against an independent oracle, but it hid the real point of a regulation example: combining independent public registers without silently conflating concepts that happen to share a spelling.

In [formal foundations](../docs/formal.md#design-theories-views-and-colimits), a colimit composes presentations along a pinned shared fragment, and a common spelling alone never identifies two kinds. In the Dutch healthcare allowance (`zorgtoeslag`), the word "partner" names three distinct notions across three boundaries:

1. **Civil partner (`civil.Partner`):** marriage or registered partnership in the civil registry.
2. **Fiscal partner (`tax.Partner`):** fiscal partnership recorded by the tax authority.
3. **Benefit partner (`toeslagpartner`):** a derived relation defined by statutory rules (`@ awr#art-5a`, `@ awir#art-3`), which agrees with neither register in every case.

This decision expands the healthcare allowance slice into a three-source flagship example with derived `toeslagpartner`, derived `insured`, derived `joint_income`, a core compiler guarantee that identically named kinds (`Partner`) across two sources never silently merge, and a readable entry point in the example learning ladder.

## 1. Expand `examples/zorgtoeslag-slice/` in place

This decision **expands `examples/zorgtoeslag-slice/` in place** once its compiler prerequisites land, rather than creating a second slice directory beside it.

- `examples/zorgtoeslag/` stays untouched as the full language design until every construct it uses (time selection, aggregates, date arithmetic, `sealed at`, `table collect`, standard money and units packs) lowers.
- `examples/zorgtoeslag-slice/` is already the runnable healthcare allowance slice with its [allowance cases](../examples/zorgtoeslag-slice/allowance-cases.yaml) and independent [reference](../examples/zorgtoeslag-slice/reference.py). Expanding it in place keeps one maintained healthcare allowance slice, preserves every existing case `S01`–`S15` with its exact expected cents or state, adds the two new cases `S16` and `S17`, and turns the slice directly into a publishable pack with `pack.yaml` and `README.md`.
- [The first slice decision](language-healthcare-allowance-slice.md) remains in force for the calculation structure, synthetic parameters, exact minor-unit arithmetic, [ordered exceptions](language-exceptions.md), [dated facts](language-dated-facts.md), and [parameter versions](language-parameters.md); this decision replaces its single-kind `Household` simplification with three composed sources.

## 2. How the three sources enter: four packs forming a colimit along `Persoon`

Each external authority is modeled as its own pinned pack under `examples/zorgtoeslag-slice/sources/`, and all three import one tiny shared kernel pack that declares `Persoon`:

```text
                zorgtoeslag-person (Persoon)
                  /          |          \
                 v           v           v
   zorgtoeslag-civil   zorgtoeslag-tax   zorgtoeslag-insurer
   (Adres, Partner,    (Inkomen,         (Polis,
    Ouder)              Partner)          PolisSoort)
                  \          |          /
                   v         v         v
                examples/zorgtoeslag-slice
       (toeslagpartner, insured, joint_income, allowance)
```

| Pack | Directory | Imports | Declarations |
| --- | --- | --- | --- |
| `zorgtoeslag-person` | `examples/zorgtoeslag-slice/sources/person` | — | `Persoon` (one synthetic identifier key `id`, e.g. `p-ann`; **never** real BSNs) |
| `zorgtoeslag-civil` | `examples/zorgtoeslag-slice/sources/civil` | `zorgtoeslag-person` | `VerbintenisSoort`, `Adres`, `Partner` (civil marriage or registered partnership), `Ouder` |
| `zorgtoeslag-tax` | `examples/zorgtoeslag-slice/sources/tax` | `zorgtoeslag-person` | `Inkomen`, `Partner` (fiscal partner) |
| `zorgtoeslag-insurer` | `examples/zorgtoeslag-slice/sources/insurer` | `zorgtoeslag-person` | `PolisSoort`, `Polis` |
| `zorgtoeslag-slice` | `examples/zorgtoeslag-slice` | all four packs above | `toeslagpartner`, `insured`, `joint_income`, `allowance`, statutory parameters |

`examples/zorgtoeslag-slice` imports the three source packs with explicit prefixes (`use zorgtoeslag-person`, `use zorgtoeslag-civil as civil`, `use zorgtoeslag-tax as tax`, `use zorgtoeslag-insurer as insurer`) and pins every pack by content hash in `pack.yaml` ([module imports](language-imports.md)).

### Why four packs instead of three modules in one pack

In `compiler/rezono_compiler/rezono_module.py`, all modules inside a single pack share one flat namespace and the compiler refuses two modules in the same pack that declare the same kind name (`Partner`). Modeling the authorities as three modules in one pack would therefore make it impossible for both the civil registry and the tax authority to declare `kind Partner`. Modeling them as three independent packs glued along one pinned `zorgtoeslag-person` pack is both the exact categorical colimit of [formal foundations](../docs/formal.md#design-theories-views-and-colimits) and the real multi-source boundary where `civil.Partner` and `tax.Partner` coexist without merging.

Isolating `Persoon` in `zorgtoeslag-person` rather than placing it inside `zorgtoeslag-civil` also keeps `zorgtoeslag-tax` and `zorgtoeslag-insurer` independent of `zorgtoeslag-civil`, so the tax and insurer packs never inherit civil `Adres`, `Partner`, or `Ouder` in their import closures.

### Current compiler and reader gaps (tracked as strict `extra:` red tests)

Inspecting the compiler (`compiler/rezono_compiler/rezono_slot.py`, `modules.py`, `native_rule_signatures.py`, `rezono_calc.py`) shows what already works and what must be completed:

1. **Works today:** Pinned multi-pack closures with diamond deduplication (`modules.imported_packs`), single-pack prefixed `use <pack> as <alias>`, engine-name qualification when two modules share a class name (`modules.Names.name`), dated facts (`facts.load(..., as_of=..., known=...)`), and ordered `unless` exceptions (`rezono_exceptions.lower_unless`).
2. **Gap 1 — Same-name kind collision across two imported packs:**
   - `rezono_slot.py:lower()` currently strips the import prefix (`civil.Partner` -> `Partner`), erasing which source a slot targets.
   - `modules.py:Names.__init__()` currently rejects any module whose import closure contains two modules declaring `Partner`, even when the Rezono module imported both packs under distinct aliases (`use zorgtoeslag-civil as civil`, `use zorgtoeslag-tax as tax`) and qualified every reference (`civil.Partner`, `tax.Partner`).
   - An unqualified reference to `Partner` when both packs are imported without aliases must produce a diagnostic that **names both candidate sources/modules** (both in schema lowering — without falsely saying "of this pack" — and in `native_rule_signatures.py`, which currently omits the candidate names from its `R046` message).
   - Covered by [same-name kind collision tests](../compiler/tests/rezono/test_same_name_kind_collision.py).
3. **Gap 2 — Inline parameter versions in `rezono_calc.py`:** `validate_param` still refuses inline versioned `param` declarations with `R050` (already tracked by [the first slice](language-healthcare-allowance-slice.md)).
4. **Gap 3 — Three-source pack, cross-source derivations, extended oracle, counterexample, and learning ladder:** Covered by [three-source healthcare allowance tests](../examples/test_zorgtoeslag_three_sources.py).

## 3. Three-source domain model

### Shared person identity

- `zorgtoeslag-person` declares `kind Persoon world closed` with one synthetic identifier key (`id`, e.g. `p-ann`, `p-bob`, `p-bea`, `p-leo`, `p-mia`, `p-noa`, `p-sam`, `p-pip`). All keys are invented synthetic strings; real BSNs or real personal records never appear in any pack, test, or case file ([working rules](../AGENTS.md)).

### Three independent sources

- **Civil registry (`zorgtoeslag-civil`):**
  - `enum VerbintenisSoort = huwelijk | geregistreerd_partnerschap`
  - `kind Adres world closed`: residential address registration (`persoon: Persoon`, `woonadres: Text`, dated per period of residence).
  - `kind Partner world closed`: civil marriage or registered partnership (`persoon_a: Persoon`, `persoon_b: Persoon`, `soort: VerbintenisSoort`, `echtscheidingsverzoek: Bool`, dated per validity period).
  - `kind Ouder world closed`: legal parent-child relationship (`ouder: Persoon`, `kind: Persoon`).
- **Tax authority (`zorgtoeslag-tax`):**
  - `kind Inkomen world closed`: taxable income (`toetsingsinkomen`) per `Persoon` (`persoon: Persoon`, `bedrag: Cents`, dated per calendar year with `valid` and `known`).
  - `kind Partner world closed`: fiscal partnership (`persoon_a: Persoon`, `persoon_b: Persoon`, `grond: Text`, dated per calendar year). This kind is strictly separate from `civil.Partner` and is never read as a benefit-partner fact.
- **Health insurer (`zorgtoeslag-insurer`):**
  - `enum PolisSoort = basis | aanvullend`
  - `kind Polis world closed`: health insurance policy (`persoon: Persoon`, `soort: PolisSoort`, dated per cover period with `valid` and `known`).

### Stored facts removed and derivations introduced

`partner: Bool` and `insured: Bool` disappear as stored facts from the schema and from the fact files. Instead, `zorgtoeslag-slice` derives all three inputs to the allowance calculation from the three sources:

1. **Derived `toeslagpartner(a, b)` (symmetric, simplified — `@ awr#art-5a`, `@ awir#art-3`):**
   `toeslagpartner(a, b)` holds for distinct persons `a` and `b` on `(as_of, known)` if and only if at least one of the following holds:
   - **Civil union without separation-plus-petition (`@ awr#art-5a`, `@ awir#art-3`):** `civil.Partner` relates `a` and `b` (in either order) AND it is **not** the case that both `echtscheidingsverzoek = true` AND `a` and `b` are registered at different residential addresses in `civil.Adres`.
   - **Cohabiting parents of a joint child (`@ awir#art-3`):** `a != b`, `a` and `b` share the same `woonadres` in `civil.Adres`, and there exists a `Persoon` `c` such that both `civil.Ouder(a, c)` and `civil.Ouder(b, c)` hold.

   This rule is an explicit simplification of Dutch statutory partnership (omitting notarized cohabitation contracts, joint home ownership, pension partners, and other Awir art. 3 grounds) and must be marked as a simplification in `examples/zorgtoeslag-slice/README.md`. Crucially, `toeslagpartner` reads only `civil.Partner`, `civil.Adres`, and `civil.Ouder`; it never reads `tax.Partner`.

2. **Derived `insured(p)`:**
   Derived from `insurer.Polis` on `(as_of, known)`:
   - `true` when `p` has an applicable `Polis` version with `soort = basis`;
   - `false` when the insurer has reported an applicable `Polis` version for `p` without `basis` (for example `soort = aanvullend` only);
   - `unknown` (`no_version_applies`) when no `Polis` version applies to `p` on `(as_of, known)` (the insurer has not reported yet — preserving explicit unknown rather than reading absence as "no").

3. **Derived `joint_income(p)`:**
   Derived from `tax.Inkomen` on `(as_of, known)`:
   - When `p` has no `toeslagpartner`, `joint_income(p)` is `p`'s own `tax.Inkomen.bedrag` (or `unknown no_version_applies` when missing).
   - When `toeslagpartner(p, q)` holds, `joint_income(p)` is `tax.Inkomen(p).bedrag + tax.Inkomen(q).bedrag`, propagating `unknown` strictly if either person lacks an income version on `(as_of, known)`.

The allowance calculation (`income_limit`, `threshold_rate`, `household_premium`, `norm_premium`, `yearly_amount`, and `allowance` with its two ordered `unless` exceptions `@ wzt#art-2.1` and `@ wzt#art-2.2`) keeps the exact formulas and statutory parameter versions of [the first slice](language-healthcare-allowance-slice.md).

## 4. Cases `S01`–`S17`, extended independent oracle, and silent-merge counterexample

### Preservation of `S01`–`S15`

All fifteen cases `S01`–`S15` in `examples/zorgtoeslag-slice/allowance-cases.yaml` keep their exact expected cents or `(state, reason)` outcomes, now computed from three-source facts:

- Single claimants (`p-ann`, `p-dex`, `p-eve`, `p-fay`, `p-gus`, `p-hal`, `p-ivy`) have no `civil.Partner` and no cohabiting co-parent; their `joint_income` is their own `tax.Inkomen`.
- `p-bob` (`S04`) is married (`huwelijk`) in `civil.Partner` to `p-bea` at the same address without a divorce petition; `tax.Inkomen` holds `2500000` for `p-bob` and `1800000` for `p-bea`, deriving `joint_income = 4300000` and `10500` cents.
- `p-kim` (`S14`) is in a registered partnership (`geregistreerd_partnerschap`) in `civil.Partner` with `p-kai` at the same address without a divorce petition; `tax.Inkomen` holds `2700000` for `p-kim` and `2400000` for `p-kai`, deriving `joint_income = 5100000 > 5020600` and `0` cents.
- `p-dex` (`S10`, `S11`) holds an `aanvullend` policy valid `2008-02-29..<2026-03-01` (`0` cents in February) and a `basis` policy valid `2026-03-01..` known `2026-02-20` (`13600` cents in March).
- `p-eve` (`S12`) holds only an `aanvullend` policy (`0` cents).
- `p-ivy` (`S13`) has no `Polis` version reported yet (`unknown`, `no_version_applies`).

### Two new cases (`S16` and `S17`)

Both new cases evaluate on `as_of: 2026-02-01`, `known: 2026-02-10` (so `standard_premium = 218000`, `threshold_income = 2960000`, `income_limit_single = 3971900`, `income_limit_partner = 5020600`):

- **Case A (`S16`) — Married in civil registry, living apart with a divorce petition (`p-leo` & `p-mia`):**
  - `civil.Partner`: `(p-leo, p-mia)`, `soort = huwelijk`, `echtscheidingsverzoek = true`.
  - `civil.Adres`: `p-leo` at `adr-leo`, `p-mia` at `adr-mia` (living apart).
  - `tax.Partner`: `(p-leo, p-mia)` is still recorded as fiscal partners for 2026 (for instance under full-year fiscal partnership election).
  - `insurer.Polis`: `p-leo` has `soort = basis`.
  - `tax.Inkomen` (2026): `p-leo = 2600000`, `p-mia = 3000000`.
  - **Expected:** `toeslagpartner(p-leo, p-mia) = false`; only `p-leo`'s own income (`2600000`) counts; monthly allowance = `floor((218000 - 1.879% * 2960000) / 1200) * 100 = 13500` cents.
- **Case B (`S17`) — Unmarried, same residential address, joint child (`p-noa` & `p-sam`, child `p-pip`):**
  - `civil.Partner`: no entry for `p-noa` and `p-sam`.
  - `civil.Adres`: `p-noa` at `adr-noa-sam`, `p-sam` at `adr-noa-sam`.
  - `civil.Ouder`: `(p-noa, p-pip)` and `(p-sam, p-pip)`.
  - `insurer.Polis`: `p-noa` has `soort = basis`.
  - `tax.Inkomen` (2026): `p-noa = 2200000`, `p-sam = 2000000`.
  - **Expected:** `toeslagpartner(p-noa, p-sam) = true`; combined income = `4200000`; monthly allowance = `floor((2 * 218000 - (4.256% * 2960000 + 13.7% * (4200000 - 2960000))) / 1200) * 100 = 11600` cents.

### Silent-merge counterexample

Case A (`S16`) is simultaneously the domain counterexample for [formal foundations](../docs/formal.md#design-theories-views-and-colimits): if a compiler or pipeline silently merged `civil.Partner` and `tax.Partner` by their shared spelling `Partner`, the fiscal partner row `(p-leo, p-mia)` (which carries no civil separation-plus-petition exclusion) would leak into `toeslagpartner`, flipping `toeslagpartner(p-leo, p-mia)` from `false` to `true`, combining `2600000 + 3000000 = 5600000 > 5020600`, and driving `p-leo`'s monthly allowance from `13500` cents down to `0` cents.

### Independent oracle

`examples/zorgtoeslag-slice/reference.py` is extended independently (Python standard library only, sharing zero code with the compiler or reader) to read the three-source facts and compute `toeslagpartner`, `insured`, `joint_income`, and `allowance` for all 17 cases `S01`–`S17`.

## 5. Readability, `README.md`, and the learning ladder

- `examples/zorgtoeslag-slice/pack.yaml` turns the slice into a publishable pack pinning the shared `Persoon` pack and the three source packs.
- `examples/zorgtoeslag-slice/README.md` opens with a short (~5-line) explanation of why "partner" means three different things here (civil partner from the civil registry, fiscal partner from the tax authority, and derived benefit partner `toeslagpartner`), marks the `toeslagpartner` rule explicitly as a simplification of `@ awr#art-5a` and `@ awir#art-3`, and notes that all person keys are synthetic (never real BSNs).
- `examples/README.md` provides the learning ladder across the example packs — from `library` (schema and facts) and `projects` (multi-file relations) through `subsidy` / `subsidy-scheme` (single-source scheme calculation and proofs) to `zorgtoeslag-slice` (multi-source colimit, same-name separation, dated facts and ordered exceptions) and `platform` (full operational system), noting `zorgtoeslag` as the full language design.

## 6. Considered alternatives

- **Adding a second slice directory (e.g. `examples/zorgtoeslag-three-sources/`) beside `examples/zorgtoeslag-slice/`.** Keeping two partial slices beside the full design `examples/zorgtoeslag/` duplicates parameters, cases, and oracles and confuses the learning ladder.
- **Putting all three sources in three modules of one pack.** A single pack shares one namespace (`rezono_module.py` refuses duplicate kind names across modules of the same pack), so `civil.Partner` and `tax.Partner` could not both be named `Partner`.
- **Placing `Persoon` inside `zorgtoeslag-civil`.** That forces `zorgtoeslag-tax` and `zorgtoeslag-insurer` to depend on `zorgtoeslag-civil`, pulling civil `Partner`, `Adres`, and `Ouder` into unrelated source packs.
- **Keeping `partner: Bool` or `insured: Bool` beside the new kinds.** Storing derived conclusions as base facts violates [working rules](../AGENTS.md) rule 9 ("Model the need, not the source").

## 7. Tests

All new expectations are recorded as strict `extra:` red tests:

- [compiler/tests/rezono/test_same_name_kind_collision.py](../compiler/tests/rezono/test_same_name_kind_collision.py):
  - `test_same_name_kinds_across_two_sources_stay_disjoint_with_qualified_imports`: two pinned source packs (`civil`, `tax`) sharing `person` (`Persoon`) and each declaring `Partner` compile cleanly under `use ... as ...` and remain two distinct kinds with distinct arrows and attributes in `bundle/schema-bundle.json`.
  - `test_unqualified_same_name_kind_reports_both_candidates`: an unqualified reference to `Partner` (in schema slots and in native rule signatures) is refused with a diagnostic naming both candidate sources, while qualified references (`civil.Partner`, `tax.Partner`) resolve to distinct engine kinds.
- [examples/test_zorgtoeslag_three_sources.py](../examples/test_zorgtoeslag_three_sources.py):
  - `test_three_source_packs_and_schema_drop_stored_partner_and_insured`: verifies the four-pack structure, distinct `civil`/`tax` `Partner` kinds, removal of stored `partner: Bool` and `insured: Bool`, synthetic keys, and `@ awr#art-5a` / `@ awir#art-3` citations.
  - `test_three_source_allowance_matches_extended_oracle_for_all_17_cases`: verifies `S01`–`S15` keep their exact amounts, `S16` (Case A = `13500`) and `S17` (Case B = `11600`) hold, and the published pack agrees with the independently extended stdlib-only `reference.py`.
  - `test_silently_merging_civil_and_tax_partner_gives_wrong_toeslagpartner_outcome`: counterexample proving that silently merging `civil.Partner` and `tax.Partner` flips Case A (`S16`) from `toeslagpartner = false` (`13500` cents) to `true` (`0` cents), while removing `tax.Partner` leaves the real derivation unchanged.
  - `test_zorgtoeslag_slice_readme_and_examples_learning_ladder`: verifies `examples/zorgtoeslag-slice/pack.yaml`, `examples/zorgtoeslag-slice/README.md` (concise three-partner explanation, simplification note, synthetic keys), and `examples/README.md` (learning ladder including `zorgtoeslag-slice`).
