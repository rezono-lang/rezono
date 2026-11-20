# Example pack `subsidy`: who receives what, and why?

A municipal energy-saving subsidy scheme: households apply with quotes for a heat pump or insulation, and the municipality pays a share of the costs that depends on their income. It is small, neutral and public, and it is the pack to copy: it uses every layer of a pack the way the engine intends. The [tutorial](../../docs/tutorial.md) builds it step by step.

Everything here is synthetic. There is no such municipality, regulation, council decision, household, issuer or person. The seven applications in `facts/applications.yaml` are written by hand; the other 233, and the payment ledger, come from `generate.py`.

The home states the scheme's evaluation day, which stays the same in the main state and every published scenario.

## Seven questions

The pack exists to answer these. Nothing is in it that none of them needs.

| # | Who asks | Question | What answers it |
|---|---|---|---|
| 1 | case officer | What does this household receive, of which costs, and why? | the calculation `award` per application, with every step and its proof down to the quote lines, the income statement and the parameter row each step read; that row names its article, and `decided_parameter` proves that the council decision behind it is in force |
| 2 | case officer | Why is this award unknown? | the named outcome `assessment`: `unknown` with a reason, never an award of zero |
| 3 | case officer | What needs a second look before I decide? | the invariant `costs_mismatch` (blocks) and the findings `repeat_application` and `maximum_applied` (do not); `maximum_applied` reads two calculation results, `entitlement` and `award`, and its proof goes down to both and to the row of `maximum_award` the award read |
| 4 | policy adviser | Who gains and who loses if the income threshold changes? | scenario `4-family-threshold` over the whole population; the finding `undecided_parameter` marks the supposed amounts as not decided |
| 5 | case officer | Did the ledger pay in October what was awarded? | the calculation `payment_difference` against the payment ledger of October, a reference source whose month is sealed |
| 6 | case officer | On whose authority do we rely on what another organisation states about a person? | `attested`, whose proof reaches the presented credential, the trust entry that let its issuer state that attribute on the day of issuance, and the lookup of the issuer's status list; the named outcome `claim_assessment` says why any other claim is `unknown` (not disclosed, an issuer without that authority, a status that is not valid) |
| 7 | case officer | Is the person another organisation states something about the person we know, and on whose word? | `attested_here`, joined across the two nodes only through `same_subject`, whose proof reaches the statement of the register that may say who is who, the trust entry that lets it, and the lookup of its status list; the named outcome `subject_identification` says per credential why its subject is `unknown` here (no statement, an issuer without that authority, a status that is not valid). Two equal identifiers of two nodes join nothing |

## The scheme in six lines

| Article | What it says | In the pack |
|---|---|---|
| 3 | The costs of the listed measures count; scaffolding does not | `cost_item.eligibility`, `eligible_costs` |
| 4 | Income threshold: € 24,000 plus € 2,000 per person. Income limit: the threshold plus € 12,000 | `income_threshold`, `income_limit` |
| 5 | Up to the threshold 40% of the eligible costs, up to the limit 24% (20% before 1 July 2026), above it nothing | `cost_share` with three definitions |
| 6 | With a registered advice report: € 150 on top of a cost share above zero | `advice_allowance` |
| 7 | At most € 5,000 per application | `award` |

Each amount and rate is a `scheme_parameter` row with its validity, its article and the decision that set it. The partial rate has two rows, because the council raised it on 16 June 2026.

## The model, kind by kind

Every base kind answers the four questions of [AGENTS.md](../../AGENTS.md) rule 9: what is its origin, can a rule derive it, does it describe another system's storage, and which question needs it.

| Kind | Origin | Why it is a fact and not a rule | Needed by |
|---|---|---|---|
| `Article` | the regulation as published | the text of a regulation is given, not derived | 1: the ground of each step |
| `Decision` (from [std-decision](../../packs/std-decision/README.md)) | a decision; who took it, when, from when it applies and how it stands are its slots | who decided what when is given | 1: every amount leads to a decider and a date |
| `ReferenceDate` (from std-decision) | a design choice of the pack: the day for which "in force" is read, 10 November 2026, the evaluation date of the calculation | a day to read the registration on is chosen, never the clock | 1, 4 |
| `EvaluationDay` (`is_a ReferenceDate`) | a design choice of the pack: the same day, stated once, with its calendar and a horizon of 90 days (the council sets next year's amounts in the last quarter, so an amount that ends within ninety days is one to decide about now) | the day and the horizon are chosen, never the clock | 4 |
| `Calendar` | a design choice of the pack: the civil calendar, whose days the regulation's dates are | an axis on which a validity and the evaluation day are compared is chosen | 4 |
| `SchemeParameter` | the decision that set it (`decision`), under an article (`article`), valid from a date until another | an amount the council chose | 1, 4 |
| `CostItem` | the regulation's list of measures and excluded costs (article 3) | the list is the regulation's choice | 1 |
| `Household` | observation: the population register, consulted when the application came in | the number of persons is observed | 1, 4 |
| `Application` | observation: the application form as received | what the applicant states | all |
| `CostLine` | observation: a line of a quote as received | what the supplier quotes | 1, 3 |
| `IncomeStatement` | observation: the income register's statement for the household | the income is observed; it is **open world** | 1, 2 |
| `AdviceReport` | observation: an entry in the advice register | the register says who took advice; it is closed world | 1 |
| `LedgerPayment` | observation: the finance department's ledger export. A **reference source**, in its own module | what another system recorded; no award reads it | 5 |
| `PeriodClose` | a decision of the finance department to close a month | the close fixes what it closed | 5 |
| `TrustEntry` | the trust list as its keeper published it, pinned by its hash (a vendor fact, Q8) | who may state what is the keeper's choice | 6 |
| `Credential` | observation: a credential as its holder presented it, its issuer's signature verified by the in port | what another party stated is given | 6 |
| `CredentialClaim` | observation: an attribute asked of a credential, with its value only when the holder disclosed it; closed world over the presentation | what the holder disclosed is given | 6 |
| `IdentityStatement` | observation: a signed statement that two identifiers, each at a node of its own, name one person; the in port verified its issuer's signature | that two identifiers name one person is what a register states; equal identifiers never say it, and whether the issuer may say it is a rule | 7 |
| `StatusLookup` | observation: the issuer's signed status list, looked up on a day, of a credential or an identity statement | whether an issuer revoked what it issued is the issuer's | 6, 7 |

What is deliberately **not** in the schema:

- **No decision kind of its own.** A decision is the same thing in every domain, so the pack imports `std-decision` and gets its kind, the rules for "in force on a date", its checks and the question "who decided this, and when?". The pack adds only the arrow from a parameter to its decision. It uses no `Subject`: no question groups decisions.
- **No award, no eligible total, no "status" field.** They follow from the facts, so they are rules. The ledger's amounts are another system's conclusions, which is why they sit in the reference module and are only compared.
- **No provenance slots.** Where a fact was recorded is its source (file and line, [S25](../../docs/compiler/import.md#provenance-per-fact-s25)), not a slot. What a reader needs as content (who decided, under which article) is a kind with its own facts.
- **No identifier that carries meaning.** `A117` is the 117th application and `H042` a household; neither says anything about the other. A parameter row is `par-06`, not "partial rate 2026-07".
- **No date a rule would have to guess.** An application has no "received on": no question here needs it. If the award had to follow the rules in force on the day of application, the date would come in then (see the limits below).
- **No knowledge time on a parameter.** A parameter row says from when it holds, not since when it was known; the date of its decision says that. None of the seven questions asks what was known on an earlier day, so no slot carries the role `known_from`, and a question "as known on 1 March 2026" would still read the rate of July.

`claimed_costs` on the application looks like a stored total, but it is an independent observation: the applicant writes it on the form, the quotes are separate documents. That is exactly why the invariant can compare them.

## Files

The scheme's definition is the pack [`subsidy-scheme`](../subsidy-scheme/README.md), which `pack.yaml` imports by path and hash: its schema (`schema/subsidy.yaml`: the scheme, households, applications, quotes and the two registers), its rules (`costs.dl`, `assessment.dl`, `scheme.dl`, `findings.dl`), the award (`rezono/award.rezono`) and their labels and sentences. It has no facts and no evaluation date. What is this pack's own:

| File | Contents |
|---|---|
| `schema/reference.yaml` | the payment ledger and its close: a reference source, layer `observation` |
| `facts/scheme.yaml` | articles, decisions, parameters and cost items, by hand |
| `facts/applications.yaml` | seven applications by hand, one for each thing the rules can say |
| `facts/population.yaml`, `facts/ledger.yaml` | 233 more applications and the October ledger, from `generate.py` (own generator, fixed seed: the same bytes on every machine) |
| `schema/credentials.yaml`, `facts/credentials.yaml` and its sources companion | what other organisations state (W4 steps 1 and 2, [trust](../../docs/ring2/trust.md#credentials-in)): written by the credential in port ([`edge/plugins/credential-in`](../../edge/plugins/credential-in/README.md)) from `credentials/`, never by hand |
| `credentials/` | the fixture the port reads: three invented issuers' public keys, a trust list, three presented credentials, two identity statements and three status lists, made once by the port's test issuer from `credentials/issue.yaml`; the private keys were never written |
| `rules/ledger.dl` | what the ledger paid per application, over accepted payments only |
| `rules/credentials.dl` | the issuer's authority on the day of issuance, the status, the named outcome `claim_assessment` and `attested`; then identity across nodes: `same_subject` from an authoritative statement, the named outcome `subject_identification` and `attested_here` |
| `rules/access.dl` | who reads what |
| `calc/date.yaml` | the evaluation date of every calculation, the scheme's included (`as_of`) |
| `calc/drift.yaml` | `payment_difference`: the ledger minus the award |
| `scenarios/*.yaml` | an income statement arrives; October is closed; a late payment is refused; the threshold is supposed otherwise |
| `labels/en.yaml`, `messages/en.mf2` | the labels and sentences of the ledger, the roles and the rules above, and the English of std-explain's questions |
| `messages/en.mf2`, `specimen/nl.mf2` | the subsidy specimen texts under `subsidy.specimen.*`. The English messages are part of the pack bundle, and the Dutch file retains the matching translation for this example |
| `reference.py` | an independent computation in exact fractions, standard library only: writes `expected/rules`, `expected/calc` and `expected/violations`, and recomputes the seal with its own row hash |
| `test_subsidy.py` | the generator gives the same bytes; the evaluation date picks the rate; who gains and loses; access per role; the invariant blocks; the credentials are what the port observes, a changed byte is refused, and `attested` rests on its three grounds; two identifiers are one person only by a statement that holds, and without one the join is `unknown` with its reason |
| `expected/compiled/`, `expected/explained/` | what the compiler makes, and the proofs with snapshots per state (both from CI) |

## The worked example: application A001

A household of three (H001) asks for a heat pump and roof insulation.

| Step | Ground | € |
|---|---|---|
| Heat pump, quoted | quote line L0001 | 8,200.00 |
| Roof insulation, quoted | quote line L0002 | 2,400.00 |
| Scaffolding, quoted but not eligible | quote line L0003, article 3 | 400.00 |
| Claimed on the form, and equal to the quotes | application A001; `costs_mismatch` is empty | 11,000.00 |
| Eligible costs | `eligible_costs` | 10,600.00 |
| Income threshold for three persons | article 4: 24,000 + 3 × 2,000 | 30,000.00 |
| Income | income statement S001 | 31,400.00 |
| Cost share: above the threshold, below the limit, so 24% | article 5, decision 2026-047 | 2,544.00 |
| Advice allowance | advice report R001, article 6 | 150.00 |
| Award, below the maximum | article 7 | **2,694.00** |

Asked as of 1 March 2026 the same application gives € 2,270.00: the partial rate was 20% then.

The other six by hand: A002 has an income exactly on the threshold (still the full rate); A003 has no income statement (unknown); A004 would get € 6,850.00 and gets the maximum; A005 is above the limit (nothing, and so no allowance either); A006 has no quote (unknown); A007 is a second application of H004, whose cost share of € 1,279.996 rounds to € 1,280.00.

## The population

240 applications of 233 households.

| | Applications |
|---|---|
| assessed, with an award above zero | 205 |
| assessed, award zero (income above the limit) | 18 |
| limited by the maximum | 24 of the 205 |
| unknown: no income statement | 14 |
| unknown: no quote | 3 |
| households with two applications (finding) | 7 |

The awards add up to € 498,007.14; the 17 unknown applications are not in that sum and not counted as zero.

**Scenarios**, each on top of the one before:

| State | What happens | What changes |
|---|---|---|
| `1-income-received` | the income statement of H003 arrives | A003 becomes known: € 786.12 at the partial rate. The ledger had paid € 1,310.20 before the statement was in: a difference of € 524.08 appears |
| `2-close-october` | finance closes October, naming 84 payments with their row hash | nothing: every payment is covered |
| `3-late-payment` | a payment booked on 30 October turns up after the close | it is refused by name (`ledger_payment__refused`) and does not count |
| `4-family-threshold` | supposed: threshold € 20,000 plus € 4,000 per person, set by a decision that is only `proposed` | `undecided_parameter` names the two supposed rows. 23 applications gain (€ 27,800.81 together), 14 lose (€ 17,609.96), 187 stay the same, 16 stay unknown |

**Drift against the ledger** (question 5). The ledger paid 77 applications in October. Three differ from the award, and one cannot be compared yet:

| Application | Ledger minus award | What happened |
|---|---|---|
| A007 | − € 150.00 | paid without the advice allowance |
| A013 | − € 419.01 | paid at the partial rate of before 1 July |
| A240 | + € 4,550.00 | paid twice |
| A003 | unknown, then + € 524.08 | paid before the income statement was in |

A difference is drift: a finding with a proof, shown to the reader. It is not an error of Rezono and it never changes an award.

## How a parameter stands on the evaluation day (std-time)

The pack imports the theory [std-time](../../packs/std-time/README.md) and reads its own facts through it, in [`views.yaml`](views.yaml) ([views that execute](../../docs/compiler/schema-operations.md#views-that-execute)): a scheme parameter is an `Interval` from `valid_from` up to, and not including, `valid_until` (both read as day counts by `days`), the evaluation day is the `ReferencePoint` (its `day` read by `yyyymmdd`, its `horizon` as it is), and the calendar is the `Axis`. There is one day, not two: the evaluation day is the `ReferenceDate` that "in force" is read on. std-time's rules then run over the scheme's facts unchanged: `begun_at`, `ended_at`, `holds_at` and `judgement` say per parameter how it stands on 10 November 2026. Seven parameters end on 1 January 2027, within the horizon, so their judgement is `attention` (`end_within_horizon`); the first partial rate (`par-05`) ended on 1 July 2026 (`negative`, `ended`). The proof of a judgement ends at the parameter's own `valid_until`, and `reference.py` computes the same rows from the dates themselves.

Left unmapped: `Series` (the pack has no kind for a parameter apart from its versions, so `allen` relates nothing), `unbounded`, `extension_end` and `known_from` (the scheme records none). The theory then says of a scheme parameter what it says of any interval without them: a validity that ended did so without an extension (`ended`), and nobody recorded from which day the parameter is known (`known_from_not_recorded`). Both rest on the absence of a row in a table of std-time itself, so a role reads them only if it reads std-time's own kinds in full: [`rules/access.dl`](rules/access.dl) grants `Interval`, `Axis`, `ReferencePoint` and `Series` to every role, and since the pack states no element of them, the grants name no element. The question `time_grounds` applies to a row of `judgement`, `holds_at` or `known_at`, so it answers why a scheme parameter stands as it does; `time_reach` applies to the theory's kind `ReferencePoint`, which no element of this pack is (the view maps the evaluation day onto it), so it does not show on an evaluation day.

## Who reads what

| Role | Reads | So it sees |
|---|---|---|
| `case_officer` | everything | awards, findings, the ledger, refused payments and drift, and what other organisations state |
| `policy_adviser` | the scheme, households, applications, quotes, both registers and the credentials; not the ledger and its closes | every award with its proof, and the whole distribution of scenario 4; no payment and no drift, not even as "unknown" |
| `propose` | what the case officer reads | the same as the case officer |
| `viewer` | what the policy adviser reads | the same as the policy adviser |
| `public` | the scheme: articles, decisions, parameters, cost items, the calendar, the reference date and the roles; no case | every amount and rate with the council decision it stands on, the proof that the decision is in force on the reference date (`decided_parameter`, `in_force_on`), and how each parameter stands on that day (`judgement`); no household, application, award, finding, payment or credential |

A role sees a conclusion only with a proof from rows it reads. The adviser's view is therefore complete for policy questions and silent about payments.

**The public.** `public` is the role of a visitor who is not signed in, a role like any other with read rules of its own ([publishing](../../docs/ring2/publishing.md#public-is-a-role), Y1.2). Every role reads the scheme, by one rule over every role per kind; the cases are given to each other role by name, because a rule over every role would give the public every case. The public does not read a few applications as worked examples either: an award is a sum over quote lines and rests on the absence of rows, and a role gets a sum or an absence only over a kind it reads in full. A role that read three applications of 240 would see three forms and no award. Worked examples for visitors therefore need a pack of their own on the same definition, which the public reads in full. `test_subsidy.py` shows that no case is named in anything the public gets, and that a new case changes none of its bytes. No profile publishes for `public` yet, so nothing is readable without a sign-in.

**Published.** Profile `edge` publishes this pack (`publish.packs` in [`deploy/profiles/edge.yaml`](../../deploy/profiles/edge.yaml)), so it is on the pilot site behind the same sign-in as the other packs. Everything in it is synthetic (see the top of this page), and it has no data class of its own, so it is `unclassified`. The profile knows two roles, `propose` and `viewer`, and a role the pack does not name reads nothing. So `facts/roles.yaml` names both, and `rules/access.dl` gives `propose` the ledger: on the site a reader sees every award and no payment, and a proposer sees the sealed month of October and the drift against it. `test_subsidy.py` holds each of the two equal to the role it reads as. The pack takes no proposals and is not held warm for live suppose.

## Running it

```bash
python -m rezono_compiler check examples/subsidy               # read the pack and load the facts
python -m rezono_compiler compile examples/subsidy generated/subsidy
python -m rezono_compiler explain examples/subsidy generated/subsidy-explained
python examples/subsidy/reference.py                         # the independent reference, per state
python examples/subsidy/generate.py                          # the population again: the same bytes
python edge/plugins/credential-in/credential_in.py observe examples/subsidy/credentials/inputs.yaml \
    --facts examples/subsidy/facts/credentials.yaml          # the credentials again: the same bytes
```

## What the pack does not have yet

- **A source and a day per observation.** Every fact here has its file and line as its source. A source companion (`facts/<file>.sources.yaml`, [S25](../../docs/compiler/import.md#provenance-per-fact-s25)) can name the register and the day of each observation, and the canonical writer changes a fact file together with its companion (S25 step 5b). Only `facts/credentials.yaml` has one, written by the credential in port; the other fact files have none yet, so the origin of their kinds is in the table above and the day an observation was made is not recorded. They are the next step: `generate.py` writes them with the facts.

## What the engine does not do yet

Recorded here instead of worked around in the pack.

- **A rule reads a calculated value only when it is known, and never sums it.** `maximum_applied` reads `entitlement` and `award` positively ([compiler](../../docs/compiler/rules.md#calculation-values-in-rules)), so an application whose award is unknown is not in it, and a maximum per household over several applications would need a sum over calculated values, which the compiler refuses by design (`calc_aggregate`). Drift stays a calculation (`payment_difference`).
- **A calculation's relation cannot have a label.** `labels/en.yaml` with `calc__award` is an error (`unknown element`), so the viewer shows calculation rules and their definitions by id, and the reason of an unknown value ("fact assessed_income.cents is missing") is the compiler's text, not a message of the pack.
- **A calculation cannot ask whether a decision is in force.** A calculation rule chooses a parameter row by its name and validity; it cannot read `in_force_on` for the decision behind that row. So the proof of an award ends in the parameter row, and the rule `decided_parameter` proves beside it that the row stands on a decision in force; a supposed amount is computed all the same and reported by `undecided_parameter`. For the same reason the day is said twice: `as_of` in `calc/date.yaml` and an `evaluation_day` row for the rules.
- **One evaluation date for all applications.** An award under the rules in force on the day of application needs an evaluation date per subject, which calculation rules do not have yet.
- **Rules cannot read dates.** No rule here says "October": `ledger_paid` adds up every accepted payment, and the ledger of this pack holds October only. The seal decides which payments still count once the month is closed; it does not pick a month. Validity is chosen by the calculation.
- **Two standard packs have no English texts.** `std-explain` and `std-access` carry Dutch only (`std-decision` has both), so `messages/en.mf2` and `labels/en.yaml` hold the English for their questions and kinds.
- **A profile cannot say that its role reads as a role of the pack.** A role of the deployment profile that the pack does not name reads nothing. Profile `edge` names `viewer` and `propose`, so the pack names those two itself beside `case_officer` and `policy_adviser`, with three read rules for `propose` ([above](#who-reads-what)). A mapping in the profile would keep a deployment's roles out of a pack's facts.
- **A sweep's grid is per slot.** All parameters share `scheme_parameter.value`, so one grid would have to fit cents and rates alike. The pack has no sweep; the supposition is a scenario.
