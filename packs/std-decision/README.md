# std-decision: the decision record

A standard pack. Much of what a registration stores as a status or a policy row is a decision by a person, and a proof should end in one: a decision, a vendor fact, a design fact or an observation ([fact classes](../../docs/compiler/import.md#fact-classes-s32), class `decision`). This pack gives every domain the same kind for it, the rules for "in force on a date", four blocking axioms, one blocking schema rule, three findings and two explanation questions. It has no facts of its own. A domain imports it like `std-access`, and its decisions are rows of the kind `Decision`.

## Concepts

The fields follow [MADR](https://adr.github.io/madr/): title, status, deciders, date and supersedes.

| Concept | Kind or slot | Meaning | Slot role or mapping |
|---|---|---|---|
| `Decision` | kind | one decision, as its record states it | |
| `title` | text, required | what was decided, in the words of the record | name (`rdfs:label`) |
| `subject` | arrow `Decision → Subject` | the matter it is about; decisions that succeed each other share it | `dcterms:subject` |
| `decider` | text, multivalued, open world | who took it: a person or a body, by the identifier the domain uses for its parties | `prov:wasAttributedTo` |
| `decided_on` | date | the day it was taken; absent while it is proposed | knowledge time (`prov:generatedAtTime`) |
| `valid_from`, `valid_until` | date | the first day it applies, and the first day it no longer does; read directly by the rules | validity (`schema:validFrom`, `schema:validThrough`) |
| `valid_from_day`, `valid_until_day` | whole number `YYYYMMDD` | retiring optional slots; no rule reads them ([limits](#limits)) | |
| `state` | `proposed`, `in_force`, `superseded` or `withdrawn`, required | the standing the record gives it today | `schema:creativeWorkStatus` |
| `supersedes` | arrow `Decision → Decision`, multivalued | an earlier decision this one replaces, from the day this one takes effect | `dcterms:replaces` |
| `reassesses` | arrow `Decision → Decision`, multivalued | an earlier decision this one looked at again; it replaces nothing. Open world: no record of a reassessment leaves unknown whether there was one | |
| `rationale` | text | why, in the words of the record; no rule reads it | `skos:scopeNote` |
| `Ground` | link kind ([S27](../../docs/compiler/import.md#link-kinds-s27)) with the ends `decision` and `rests_on` | one decision rests on another: its record names the other as a ground | `prov:wasInfluencedBy` |
| `warrant` | arrow `Decision → Principle`, multivalued | a principle the decision rests on; no rule reads it | |
| `owner` | text, multivalued, open world | who answers for the decision today (not the decider); no rule reads it | `schema:maintainer` |
| `review_on` | date | the day the decision is looked at again | |
| `Purpose` | kind, with an arrow to its `Decision` | something the decision serves (`title`), and for whom (`served`, open world) | |
| `Principle` | kind, with an arrow to the `Decision` that adopted it | a statement that makes decisions right; it stands as that decision stands | |
| `Alternative` | kind, with an arrow to its `Decision` | an option that was weighed and rejected, with the `reason` | |
| `Exception` | kind, with an arrow to its `Decision` | something the decision leaves out, in the words of the record | |
| `Subject` | kind | a matter that is decided on, named by the domain | |
| `ReferenceDate` | kind, with `date` (`Date`, required; `day` is retiring) | a day for which the registration is read; a fact, never the clock | |

There is no free-text field that stands for structure: who, when, from when, until when, the state and the predecessor each have a typed slot. The rationale is text and stays text.

**What a decision rests on.** A `Ground` is a row of its own, so its source is the record that names it, apart from the source of the decision it points to. The pack follows the grounds (`ground_chain`) and holds them to one axiom: they have no cycle. It says which record is a proposal (`proposal`), because a proposal names grounds as a decision does. It has no rule on what still stands or what to look at again: a domain that asks what a decision rests on, or what to reassess when a ground no longer stands, writes that rule itself and reads `ground_chain`, `in_force_on`, `ended`, `replaced` and `withdrawn_without_start`, never the state. Those rules move here when a second domain needs them.

**The subject of a decision, and what a decision sets.** `subject` names the matter. The facts a decision sets are the domain's own: a domain kind points to its decision with an arrow of range `Decision` (`decision: {range: Decision, required: true}`), and a rule of the domain reads `in_force_on` through it. The pack cannot name a domain's kinds, so that arrow belongs to the domain.

## The justification layer

An explanation that says why needs more than the decision: what it serves, which principle makes it right, what was rejected, what is excepted, who answers for it and when it is looked at again ([explanation contract](../../docs/explain/contract.md#the-second-level-why), EX9). These are recorded facts with their own source, and they point to the decision they belong to.

| Part of an explanation | Where it is |
|---|---|
| Purpose | rows of `Purpose` that point to the decision |
| Warrant | the `Principle` rows the decision names in `warrant` |
| Backing | the decision itself: title, state, decider, date |
| Rejected alternatives | rows of `Alternative` |
| Exceptions | rows of `Exception` |
| Owner and review | `owner` and `review_on` on the decision |

**No rule reads the layer.** A conclusion rests on `in_force_on`; the layer is shown beside the proof, per role like every other row. So a missing purpose changes no conclusion, and the explanation lint counts what is missing.

**A principle has no state of its own.** It stands as the decision that adopted it stands (`Principle.decision`): proposed while that decision is proposed, in force while it is in force on the reference date. A principle without such a decision is of unknown standing, and an explanation says so.

**A domain may add to a principle.** What a principle means for the domain's own rules (for traffic, for money) is the domain's: it declares a subkind of `Principle` with that slot (`is_a: Principle`), so its rows are rows of `principle` and a rule of the domain reads the subkind's slot. A principle a rule reads must still have its `decision`, and the rule reads `in_force_on` through it.

**Not here:** which relation a principle closes (a default deny, so that an explanation can say what is not allowed and why). That is the marker `@closes` on the domain's closing relation, whose rule names the principle in force (question `contrast`); a slot that names a relation would put a definition into data.

## Rules

All in [`rules/decision.dl`](rules/decision.dl). Time comes from the validity days and from `supersedes`, never from the state. The state is what the record says today, and a reference date may lie before or after today.

| Relation | Holds when |
|---|---|
| `took_effect(decision, on)` | the record does not say `proposed`, and its first day is on or before the reference date |
| `ended(decision, on)` | its `valid_until` day is on or before the reference date |
| `replaced(decision, by, on)` | `by` supersedes it and has taken effect on the reference date; it stays so when `by` itself ends |
| `in_force_on(decision, on)` | it took effect, has not ended, and is not replaced on the reference date |
| `replaces(a, b)` | `a` supersedes `b`, directly or through decisions in between |
| `ground_chain(decision, rests_on)` | the record of the decision names the other as a ground, directly or through decisions in between; it says nothing on whether either is in force |
| `proposal(decision)` | the record says `proposed`: it has not been taken |

So a decision whose record says `superseded` is in force on a reference date before its successor took effect, and a decision whose successor starts next year is in force until then.

## Axioms

`@invariant` relations: any row blocks publication.

| Axiom | Relation |
|---|---|
| A superseded decision is not in force | From the day a successor takes effect, `in_force_on` cannot hold (the rule above; the tests check it on every engine). What is left is a record that says `superseded` while no decision that was taken and names its first day supersedes it. By the rules it is then in force, against its own record: `superseded_in_force(decision, on)` |
| `supersedes` has no cycle | `supersession_cycle(decision)`: a decision that replaces itself |
| A decision does not end on or before the day it starts | `window_inverted(decision)` |
| The grounds have no cycle | `ground_cycle(decision)`: a decision that rests on itself. A fact also changes through a proposal, so this is an axiom of the pack and not a test of one import |

One LinkML rule on `Decision` blocks too: a decision that applied and was withdrawn names the day it stopped applying.

## Findings

They ask for attention and do not block ([concepts](../../docs/concepts.md#inferences-findings-and-coverage-gaps)).

| Finding | Relation |
|---|---|
| A decision in force without a decider | `in_force_without_decider(decision, on)`. `decider` is open world, so this is `@absence`: somebody decided, and the record does not say who |
| A record that says in force and names no first day | `in_force_without_start(decision)`. Such a decision is in force on no reference date, so the finding says why it is missing |
| A record that says withdrawn and names no first day | `withdrawn_without_start(decision)`. By its days it was in force on no reference date and no day says when it stopped, yet another decision may rest on it. A rule that asks whether a ground still stands reads this relation. A withdrawn record that names its days needs none: `ended` says when it stopped |

## Questions

[`questions.yaml`](questions.yaml) narrows the generic `grounds` and `reach` of [std-explain](../std-explain/questions.yaml) to decisions. A filter names relations only, because that is what the gate serves today.

| Term | Asks | Answer |
|---|---|---|
| `decided` | Who decided this, and when? | from a conclusion back to each `in_force_on` it rests on, and on to that decision itself: `took_effect` reads `decision(d)`, so the walk ends in the record. Who and when are fields of that record, and its sources end the walk |
| `replaced` | What did this decision replace? | the decisions it supersedes, directly and through others (`replaces`), and those it has replaced on a reference date (`replaced`), ring by ring |

## Worked example

A reading room decides on its opening hours three times, and once for one summer.

```yaml
subject:
  - {id: opening-hours, title: Opening hours of the reading room}
decision:
  - {id: hours-2024, title: The reading room is open on weekdays, subject: opening-hours, decider: [board],
     decided_on: "2024-02-12", valid_from: "2024-03-01", state: superseded}
  - {id: hours-2025, title: The reading room is also open on Saturday, subject: opening-hours, decider: [board],
     decided_on: "2025-06-10", valid_from: "2025-07-01", state: in_force,
     supersedes: [hours-2024], rationale: Visitors asked for it in the survey of 2025.}
  - {id: hours-2027, title: The reading room is closed on Monday, subject: opening-hours, state: proposed,
     valid_from: "2027-01-01", supersedes: [hours-2025]}
  - {id: summer-2026, title: Shorter hours in the summer of 2026, subject: opening-hours,
     decided_on: "2026-05-20", valid_from: "2026-07-01", valid_until: "2026-09-01", state: in_force}
reference_date:
  - {id: "2025-01-01", title: 1 January 2025, date: "2025-01-01"}
  - {id: "2026-08-01", title: 1 August 2026, date: "2026-08-01"}
  - {id: "2026-11-10", title: 10 November 2026, date: "2026-11-10"}
```

| Reference date | In force | Why |
|---|---|---|
| 1 January 2025 | `hours-2024` | its record says superseded today, but `hours-2025` took effect only on 1 July 2025 |
| 1 August 2026 | `hours-2025`, `summer-2026` | `hours-2024` is replaced by `hours-2025`; the summer decision runs from 1 July to 1 September |
| 10 November 2026 | `hours-2025` | the summer decision has ended; `hours-2027` is proposed, so it replaces nothing yet |

One finding: `in_force_without_decider(summer-2026, 2026-08-01)`, because that record names nobody. No axiom has a row. [`test_std_decision.py`](../../compiler/tests/test_std_decision.py) reads this block and checks this table.

## Using it in a domain

1. Import it in `pack.yaml`, pinned on its hash (`python -m rezono_compiler hash packs/std-decision`).
2. Write decisions as rows of `decision`. Where the record gives only a date, `valid_from` is that date.
3. Point each domain kind that a decision sets to its decision with an arrow of range `Decision`.
4. Add at least one `reference_date` row. It is a choice of the domain, not the clock.
5. Rest conclusions on `in_force_on`, not on `decision__state`: `allowed(x, r) :- thing__decision(x, d), in_force_on(d, r).`
6. Grant `may_read` on `decision`, `ground`, `subject` and `reference_date` to the roles that may see them ([std-access](../std-access/rules/access.dl)), and on `purpose`, `principle`, `alternative` and `exception` where the domain records them.
7. The pack has English and Dutch labels and sentences. A domain replaces any of them with an entry of the same id.

## One pack, not two: std-justification

The paused branch `claude/ex9-justification` drafts a pack `std-justification` (EX9) with the kinds `Justification`, `Principle`, `Decision`, `Alternative` and `Exception`. There is one standard pack for decisions, and it is this one.

- **Brought in here:** its `Decision`. Title, state, date and decider are the same fields; `settled` is `in_force` here; `rationale` moved from `Justification` to the decision it belongs to. Validity, `supersedes`, the subject and the rules are new.
- **Reversed:** the draft says no rule reads its kinds (K01). The owner's review of 10-11-2026 says the opposite for decisions: a decision is a premise, and a proof ends in one. So the rules here read `Decision`, and a domain's conclusion rests on `in_force_on`.
- **Brought in since (EX9, 11-11-2026):** `Principle`, `Alternative` and `Exception`, and a new `Purpose`, as kinds with an arrow to `Decision` ([the justification layer](#the-justification-layer)). The draft's `Justification` is gone: it hung every part on a free-text `about`; here each part points to its decision with a typed arrow. A principle lost its own state: it stands as the decision that adopted it.
- **Not brought in, and why:** the marker `// @closed_by`, the `closes` slot of a principle and lint class M. They belong to the computed contrast (EX11) and come with it.

## Limits

- **Retiring day-number slots.** The rules compare `valid_from`, `valid_until` and `ReferenceDate.date` as native dates. The legacy `valid_from_day`, `valid_until_day` and `ReferenceDate.day` slots stay optional and unread during the migration and are removed in 0.3.0.
- **In force is read on reference dates only.** Without a `reference_date` row nothing is in force, and `superseded_in_force` has no row.
- **A stale `in_force`.** A record that still says `in_force` after its successor took effect is not reported: on a later reference date that is simply history, and the rules already leave it out of `in_force_on`.
- **The proof-leaf check** (every leaf has a fact class) is a model check, not part of this pack.

## Standards

| std-decision | MADR | PROV-O and Dublin Core |
|---|---|---|
| `Decision` | a decision record | `prov:Entity` |
| `title` | title | `rdfs:label` |
| `state` | status | `schema:creativeWorkStatus` |
| `decider` | deciders | `prov:wasAttributedTo` |
| `decided_on` | date | `prov:generatedAtTime` |
| `supersedes` | "superseded by", read the other way | `dcterms:replaces` |
| `rationale` | context and decision drivers | `skos:scopeNote` |

The alignment is a comparison table and mapping annotations, not an export.
