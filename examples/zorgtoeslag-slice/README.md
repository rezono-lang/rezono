# Healthcare allowance slice (`zorgtoeslag-slice`)

In Dutch healthcare allowance (`zorgtoeslag`), the word "partner" names three distinct notions across three boundaries: a **civil partner** (`civil.Partner`, marriage or registered partnership in the civil registry), a **fiscal partner** (`tax.Partner`, recorded by the tax authority), and a derived **benefit partner** (`toeslagpartner`, defined by statutory rules).
Silently merging `civil.Partner` and `tax.Partner` by spelling produces the wrong benefit outcome when spouses live apart with a divorce petition yet remain fiscal partners for the calendar year.
This pack glues three independent source packs (`zorgtoeslag-civil`, `zorgtoeslag-tax`, `zorgtoeslag-insurer`) along one shared `zorgtoeslag-person` pack (`Persoon`), keeping `civil.Partner` and `tax.Partner` disjoint while deriving `toeslagpartner`, `insured`, `joint_income`, and the monthly `allowance`.
All person keys (`p-ann`, `p-leo`, `p-noa`, ...) are synthetic identifiers — never real BSNs or real personal records.
The `toeslagpartner` rule is an explicit **simplification** of Dutch statutory partnership (`awr#art-5a` and `awir#art-3`), modeling civil unions (excluding living apart with a divorce petition) and unmarried cohabiting parents of a joint child while omitting notarized cohabitation contracts, joint home ownership, pension partners, and other statutory grounds.

## Sources and composition

Four pinned packs under `sources/` form a colimit along shared `Persoon`:

- `sources/person` (`zorgtoeslag-person`): shared synthetic `Persoon`.
- `sources/civil` (`zorgtoeslag-civil`): `Adres`, `Partner` (`VerbintenisSoort`: `huwelijk | geregistreerd_partnerschap`, `echtscheidingsverzoek`), and `Ouder`.
- `sources/tax` (`zorgtoeslag-tax`): `Inkomen` (`bedrag` in euro cents) and distinct `Partner` (fiscal partner, never read by `toeslagpartner`).
- `sources/insurer` (`zorgtoeslag-insurer`): `Polis` (`PolisSoort`: `basis | aanvullend`).

## Derived rules and calculation

- `rules/allowance.dl` derives `toeslagpartner` (`@ awr#art-5a`, `@ awir#art-3`), `insured_flag`, and `joint_income` from the three sources without any stored `partner: Bool` or `insured: Bool`.
- `rezono/allowance.rezono` derives `insured`, `income_limit`, `threshold_rate`, `household_premium`, `norm_premium`, `yearly_amount`, and `allowance` with two ordered `unless` exceptions (`@ wzt#art-2.1` and `@ wzt#art-2.2`).
- `allowance-cases.yaml` and the independent standard-library oracle `reference.py` verify all 17 cases (`S01`–`S17`), including Case A (`S16`: married, living apart with a divorce petition, still in `tax.Partner` -> `13500` cents) and Case B (`S17`: unmarried cohabiting parents of a joint child -> `11600` cents).
