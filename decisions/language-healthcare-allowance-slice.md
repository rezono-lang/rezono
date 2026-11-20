# The first slice of the healthcare allowance (zorgtoeslag)

Regulation is the first domain after the reference platform, and `examples/zorgtoeslag` is its example. That example is written in the language and is not published. It has no `pack.yaml`, and its module uses nearly every construct the language designs, some of which the compiler refuses or the reader reserves. This decision cuts a first slice that can publish once three building blocks lower, and says where every other construct goes.

## What the healthcare allowance adds to the subsidy example

`examples/subsidy` with `examples/subsidy-scheme` is already a regulation in the existing pack form. It evaluates one scheme on one evaluation day for the whole pack. Its amounts and rates are rows of a fact kind, `scheme_parameter`, each with its validity. The award is a list of ordered definitions in `calc/award.yaml`, and its facts have no versions.

The healthcare allowance adds:

- an entitlement per month, each month evaluated on its own day, and months that are sealed and then get correction rows;
- facts that hold for a period and become known on a day: an income estimate per year, corrected later and back to the start of the year;
- parameter versions written in the text itself, with `valid` and `known`, including an amendment that replaces a version on the same dates;
- ordered exceptions that override a computed amount, each with its article, and that keep an unknown condition apart from a decided zero;
- a household of a claimant and a partner, with counts and sums over its members;
- an age computed from a date of birth, and grounds for refusal collected in a table.

## The first slice

The first slice uses three building blocks that no other pack uses:

- **ordered exceptions:** `unless` blocks under a derived value, each line with its source ([ordered exceptions](language-exceptions.md));
- **dated facts:** fact rows with `valid` and `known` ([dated facts](language-dated-facts.md));
- **inline parameter versions:** a parameter with a version per year, each with `valid` and `known` ([parameters](language-parameters.md)).

Beside them it uses only what the language already reads and the compiler lowers or is about to lower: a kind with Boolean and amount slots, a fact table, a unit, and a derived value with arithmetic, comparisons, `when … then … else` and `floor`.

The slice keeps one kind, `Household`. Its slots are `partner` (a Boolean in the fact table), `insured` (a dated Boolean, a version per period of cover) and `joint_income` (a dated amount, a version per calendar year). The four parameters of the full example, `standard_premium`, `threshold_income`, `income_limit_single` and `income_limit_partner`, keep their versions per year, including version 3 of the standard premium, known later on the same dates. The derived value `allowance` has two `unless` blocks: `not insured` gives zero, and below it `joint_income > income_limit` gives zero, so the income block is read first (v0 section 5b). The amounts, rates and versions are those of the full example. They are illustrative.

A publication of the slice is evaluated on one day, with one `as of DAY known DAY` line, as in the subsidy example. Each case of the slice evaluates one household on the first day of one month.

### How the slice writes an amount

An amount is a whole number of cents of the unit the slice declares itself: `unit Cents = money minor EUR` ([units](language-units.md)). EUR 2,180.00 is written `218000`. A rate is a percentage literal, such as `1.879 %`, which a calculation reads as an exact ratio. Arithmetic is exact until the one rounding the regulation names: the monthly allowance is rounded down to whole euros, written in the derived value as `floor(yearly / 1200) * 100`. The slice has no `rounding` declaration and imports no standard pack.

## Every other construct

| Construct of the full example | In the slice |
| --- | --- |
| `unless` with its article | In the first slice. The exception for a minor comes later, with date arithmetic. |
| Facts with `valid` and `known` | In the first slice: `insured` per period and `joint_income` per year. |
| Parameter versions in the text | In the first slice. |
| `applies at` | Later, after the three building blocks of the slice publish. It moves the evaluation day from the publication to the record. Until then a publication has one `as of` line. |
| `sealed at` and correction rows | Later, after `applies at`, together with the form of a correction row. Without it a correction changes an earlier month too, as case S08 shows. |
| The time selection `income at first_day` (`R015`) | Rewritten. A dated fact is selected on the evaluation day like any dated fact, so the slice reads `joint_income` without a selection. The explicit selection comes later, after `applies at`. |
| Date arithmetic `birth_date + 18 year` with `rounding date down` | Later, after `applies at`. The slice has no exception for age. |
| `use std.money`, `use std.units` | Rewritten. The slice declares `unit Cents = money minor EUR`. The standard packs come later, after a dotted pack name lowers ([imports](language-imports.md)) and those packs exist. |
| A `rounding` declaration | Rewritten as an explicit `floor` in the derived value. The declaration comes later, after calculated values lower, since it lowers with the calculations that use it ([units](language-units.md)). |
| A `reason` declaration | Later, with the decision on named reasons (#919). In the slice a value that is not known has no version, which gives `unknown no_version_applies`. |
| The checks `claimant_is_member` and `allowance_cap` | Later, after conditional checks lower (`compiler/tests/rezono/test_lower_conditional_check.py`). `claimant_is_member` also needs the inverse reference. |
| The table `threshold_rate`, with a derived value as input and a number as output | Rewritten as `when partner then 4.256 % else 1.879 %`. A table in a calculated value comes later, after a decision admits it ([calculated values](language-calculations.md) refuses it with `R050`). |
| The table `grounds`, with a comparison as input, and `enum Ground` | Later, after a table can take a comparison as input and the policy `collect` publishes. |
| Counting and summing over the members of a household | Rewritten. `partner` is a fact of the household, and `joint_income` is one dated fact of the household rather than a sum over its members. Aggregates come later, after a decision admits them in a calculated value. |
| The state test `is n/a`, and the optional dates `insured_from` and `insured_until` | Rewritten. `insured` is a dated Boolean with an explicit `false`, so no state test is needed. State tests in a calculated value come later, with the same decision as the aggregates. |

What is decided and not yet published:

| Decided | In the slice |
| --- | --- |
| Calculated values ([calculated values](language-calculations.md)) | The slice waits for them: the allowance is a derived value (`compiler/tests/rezono/test_lower_calculation.py`). |
| The inverse reference ([inverse references](language-inverse-references.md)) | Left out, together with the list of members. |
| The table policy `collect` ([tables](language-tables.md)) | Left out, together with the grounds. |

## Where the slice lives

The slice is a pack of its own beside the full example: `examples/zorgtoeslag-slice`. It holds the module `rezono/allowance.rezono`, the facts `facts.rezono`, the expected outcomes `allowance-cases.yaml` and the oracle `reference.py`. It gets its `pack.yaml` when its module compiles, after the third step below. Until then no pack check reads it. Its cases are not named `cases.yaml`: that name holds the cases of the reader (`rezono/test/examples.test.ts`), with `compile` and `form` outcomes, while these are values for the oracle and the published pack.

`examples/zorgtoeslag/zorgtoeslag.rezono` and its `cases.yaml` stay a design until every construct of the full example is there. Then the full example gets its own `pack.yaml`, and its cases become claims about the published pack.

## The oracle

The oracle of the slice is `examples/zorgtoeslag-slice/reference.py`, an independent calculation in the manner of `examples/subsidy/reference.py`. It uses the standard library only and shares no code with the compiler or the reader. It reads the fact rows of `facts.rezono` with its own reading, and it states the parameter versions itself, from this decision, rather than reading the module. Its function `allowance(facts, household, as_of, known)` gives the monthly allowance in cents, or the pair of state and reason. The cases in `allowance-cases.yaml` were computed by hand, and the oracle must give each of them. The oracle is evidence: it lands with the tests, apart from the module it checks, and was written without reading that module.

A lowering test of each building block of the slice compares what the compiler publishes with the oracle, not with the compiler's own output.

## The order of the decisions on publishing

Each building block of the slice gets its own decision on how it lowers and publishes, and then its lowering test against the oracle, in this order:

1. **Inline parameter versions.** The calculation model already selects parameter rows by `valid` and `known` (`parameter_choice`), so only the rows are new: the decision says how a version in the text becomes a row.
2. **Ordered exceptions.** The calculation model has no operator for `unless` yet. The decision gives one, or a lowering into the existing operators that keeps the states of v0 section 5b.
3. **Dated facts.** The fact contracts need a place for versioned values ([dated facts](language-dated-facts.md)), which is the largest change of the three.

After the third, the slice gets its `pack.yaml`, and a test publishes every case of `allowance-cases.yaml` and compares it with the oracle (`test_published_slice_gives_the_oracle`).

Here the choice of the domain goes before usage. Otherwise the order of the language follows usage: a building block publishes when the conversion of a pack waits for it, as the pack table of `scripts/language_usage.py` and [first packs](language-first-packs.md) show. These three building blocks are used by no other pack, so that order would put them last.

## Considered

- **Rewriting `examples/zorgtoeslag` itself.** The slice would replace the design of every construct that is not there yet, and the cases that describe them.
- **Publishing the whole example at once.** Nothing would publish before the time selection, the aggregates, date arithmetic and the standard packs were all there.
- **Amounts with a standard money pack.** No such pack exists, and the compiler refuses a dotted pack name.
- **Keeping the exception for a minor with a dated fact `adult`.** That moves a rule into the data. The exception returns with date arithmetic.
- **An oracle that reads the module.** It would test the module against itself.

## Tests

`compiler/tests/rezono/test_zorgtoeslag_slice.py` holds two red tests. The oracle is not a task of its own: it is the expectation of the published module, and a test cannot wait for evidence it reads.

- `test_published_slice_gives_the_oracle`: first the oracle, with the standard library only, gives every case of `allowance-cases.yaml` and follows a change in the facts it reads; a wrong oracle fails the test outright rather than leaving it red. Then the published pack gives, for every case on its own `as of` day, the allowance the oracle gives, with both evaluators of the calculation agreeing. It stays red until the slice has its `pack.yaml`, after the three building blocks publish, so it is no task before then.
- `test_slice_module_uses_only_the_first_slice`: the module reads, belongs to the pack `zorgtoeslag-slice`, uses the three building blocks with a parameter version per year and two `unless` blocks, and uses nothing outside the first slice.
