---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-rezono-1-aggregate-spelling
---

# Rezono 1: one spelling per purpose for aggregates, and four-state folding

[The first-release decision](language-rezono-1.md) adopts `.where(pred)`, `.count(pred)` and a relation as its tuple set for `rezono 1`. It leaves two loose ends in counting. It does not say whether the positional spelling with `_` stays beside the new form. And it requires strict four-state aggregates, while the checker's fold still skips `not_applicable` without knowing which language version a program comes from. This decision settles both. It changes nothing in `rezono 0`.

## 1. One form per purpose

The [language reference](../docs/rezono/v0.md#2-settled-choices), §2, settles "aggregates: method form only, no comprehension". [The first-release decision](language-rezono-1.md#what-ships-in-rezono-1-vs-later-vs-refused) adds the tuple-set method form, with bare column names, but does not say whether the positional spelling (`r(a, _, _).sum(it.cents)`) stays beside it. The constraint "One core, one way" of [readable rules](language-readable-rules.md) asks for one way to write each thing. So each purpose gets one form:

| Purpose | Form in `rezono 1` | Example |
|---|---|---|
| Test that a row exists, or that a tuple is a member | a positional relation call, with `_` for a column it does not bind | `line(a, _, _, _)`, `Service.where(provides(it, f, _)).one()` |
| Count, sum, take the minimum or maximum over, or filter the rows of a relation | the tuple-set method form, with the relation's declared column names | `r.where(col = …)`, `r.count(pred)`, `r.sum(col)`, `r.min(col)`, `r.max(col)` |

- **The positional call stays.** It is the form for a membership or existence test, in `rezono 1` as in `rezono 0`. `_` stays a token, as the decision of 2026-11-19 cited in [readable rules](language-readable-rules.md) requires. That decision is not reopened, and no word is added for `_`.
- **Rows as a set use the tuple-set form.** A relation name stands for its tuple set, and inside `.where(...)` and the aggregate methods its declared column names are in scope without `it.`, as [the first-release decision](language-rezono-1.md#3-effect-on-prior-decisions) §3.4 and [the first-release proposal](../docs/rezono/first-release-proposal.md) §1 item 2 give it. A kind is the tuple set of its elements, with its slots as columns (`Application.count(household = h)`).
- **The positional aggregate is removed in `rezono 1`.** In a `rezono 1` module, a relation call with at least one `_` argument that stands in an aggregate's collection position is `R028`. The collection position is the receiver of an aggregate method (`count`, `sum`, `min`, `max`, `any`, `all`, `none`, `one`), directly (`r(a, _).count()`) or through a filter whose result is that receiver (`(r(a, _) where p).count()`, `r(a, _).where(p).count()`). A call inside a predicate, such as `provides(it, f, _)` above, is a membership test and stays.
  - The diagnostic's span is the positional call.
  - Its hint is `hint.use_instead` with the tuple-set spelling. That spelling starts with the relation or kind name followed by `.where(` or by the aggregate method and `(`. Where the module declares the relation's columns, the hint is the whole `rezono 1` spelling, as in the table below.
  - As with every `R028`, the module is not read: there is no module form and no other diagnostic ([module reader](../rezono/src/module.ts)).

### The three positional aggregates of the native rules

[Native rules](language-native-rules.md#4-constructs-and-evidence), §4, writes counting, filtering and summing with a positional call. Each one has one `rezono 1` spelling, with the column names that the subsidy examples declare:

| `rezono 0` (native rule) | `rezono 1` | Declared columns |
|---|---|---|
| `n = Application.household(_, h).count()` | `n = Application.count(household = h)` | kind `Application` with slot `household: Household` (`examples/subsidy-scheme/schema/subsidy.yaml`) |
| `n = (line(a, _, _, _) where it.cents = 0).count()` | `n = line.count(application = a and cents = 0)` | `line(application, cost_line, item, cents)` (`examples/subsidy-scheme/rules/costs.dl`) |
| `t = ledger_line(a, _, _).sum(it.cents)` | `t = ledger_line.where(application = a).sum(cents)` | `ledger_line(application, payment, cents)` (`examples/subsidy/rules/ledger.dl`) |

In `rezono 1` these stand in the body of a derived value, for example `derived paid: Int = ledger_line.where(application = a).sum(cents)` under `extend a: Application`, because `rule ... when ...` is itself `R028` there. `r.count(pred)` is `r.where(pred).count()` and lowers to the same IR; both spellings are adopted by the first-release decision, and this decision does not choose between them.

### Rows, not values

A tuple set is a set of rows, and a row is identified by all its columns. An aggregate reads one contribution per row:

- `ledger_line.where(application = a).sum(cents)` adds two payments of the same amount twice, because `payment` is part of the row. [Native rules](language-native-rules.md#4-constructs-and-evidence) already states this for the positional spelling ("Equal amounts in different payments both contribute"), and it holds unchanged for the tuple-set spelling. A sum is never taken over the distinct values of a column.
- `line.count(application = a and cents = 0)` counts whole line keys, as the positional spelling does.
- `Application.count(household = h)` counts applications, one per element.

A row of a `Bool` relation such as `line` or `ledger_line` is a proven tuple, and each of its columns is known. On the same rows, the `rezono 1` spellings of the second and third example give the `rezono 0` results. A kind's slot can hold a value in a state. In `rezono 1` the filter `household = h` is strict in that state (section 2): an application whose household is unknown leaves the count unknown, where the `rezono 0` slot read counted only the rows it had. That difference is intended. An author who means to count only applications with a known household writes `Application.where(household is known).count(household = h)`.

### `rezono 0` keeps its spelling

In `rezono 0` the three positional spellings keep their meaning and give no `W107`. The tuple-set form does not exist there (`where` is a keyword, so `r.where(` does not read), so a warning would have no replacement to name. This follows [the first-release decision](language-rezono-1.md#1-fixed-invariants-and-scope) §1 for `table priority`: `rezono 0` is the workbench, and the phased deprecation of [the language reference](../docs/rezono/v0.md#4b-language-version-and-deprecation) §4b starts at `rezono 1`.

## 2. Four-state folding

**`rezono 1` (`rezono.rules/2`).** `count`, `sum`, `min` and `max` are strict in the states of their members and of their memberships, as [expressions](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) Appendix A.3 and [the first-release decision](language-rezono-1.md#4-lifted-across-strata-requires-a-mandatory-closed-domain-not-an-open-calculation-selection) §5 item 4 require. The result of an aggregate is:

1. `invalid` if a member is `invalid`;
2. otherwise `unknown` if a member is `unknown`;
3. otherwise `not_applicable` if a member is `not_applicable`;
4. otherwise the value computed from the known members: a sum or count of no members is `0`, and the minimum or maximum of no members is `not_applicable empty`.

The reason and cause are those of Appendix A.4. An author who means to leave out members in a state says so with a filter, `.where(it is known)`, so that nothing is skipped silently.

**`rezono 0` (`rezono.rules/1`, and the checker's form without `format`).** The rule of [the formal foundations](../docs/formal.md#6-calculation-unknown-and-money) §6 stays, as the checker applies it today: `invalid` blocks, `unknown` is strict, and `not_applicable` does not count. A sum skips it, and a minimum or maximum with only `not_applicable` members is `not_applicable`. A count of rows reads no cell and is the number of rows. Existing publications, their proofs and their checker results keep their meaning (v0 §4b).

This settles the case `[known 7, n/a]` that [native rules](language-native-rules.md#12-compatibility-and-deferred-state-support) §12 leaves open, per format: the sum is `known 7` in `rezono.rules/1` and `not_applicable` in `rezono.rules/2`. The value case `agg-na-member` of `docs/semantics/value-cases.yaml` records the same choice once its status is updated.

### The checker's fold knows the format

`_fold` in `checker/rezono_checker/evaluate.py` folds without knowing where a program comes from. So:

- `load_rules` (`checker/rezono_checker/rules.py`) accepts `rezono.rules/2` and records the format of the program it reads. This waits for the `rezono.rules/2` IR of [the first-release decision](language-rezono-1.md#4-underlying-ir-witnesses-checker-and-engines-rezonorules2) §4; today it refuses the format.
- `recompute` in `check.py` and the closure pass in `closure.py` fold every aggregate under the format of its program.
- `_fold` takes the format as an argument. Without one it folds strictly, as for `rezono.rules/2`. The call without a format in `checker/tests/test_functional_derivation_checker.py` then stays valid as written, and a caller that forgets to pass `rezono.rules/1` gives a result that disagrees with the engine and is found, never a state that is skipped in silence. Every `rezono.rules/1` and format-less caller passes its format.
- A `count` that counts rows reads no cell in either format. Where the `rezono.rules/2` IR gives a count a value column to read, it folds that column as a sum does. No test covers this yet; it is specified here for the `rezono.rules/2` contract.

The SQL lowering of `rezono.rules/2` folds the same way (`compiler/tests/test_functional_derivation_engines.py`), so the engines and the independent checker agree. A change to `checker/rezono_checker/` is read before it lands ([checker and access review](checker-and-access-review.md)); this decision changes no file there.

## Tests

| Test | Mark | What it holds |
|---|---|---|
| `rezono/test/test_rezono_1_aggregate_spelling.py`, `test_rezono_1_refuses_positional_aggregates` | `M3`, waits for `rezono/test/test_rezono_1_derived.py` | For each of the three examples, a `rezono 1` module with the positional aggregate is refused with one `R028` at the positional call and a tuple-set hint, and the same module with the `rezono 1` spelling (and, for `line`, a positional existence test beside it) is read as `rezono.module/5` without diagnostics. |
| `rezono/test/test_rezono_1_aggregate_spelling.py`, `test_rezono_0_keeps_positional_aggregates` | green guard | A `rezono 0` module with the three native rules reads as `rezono.module/3` without diagnostics, so without `W107`, and keeps each aggregate over its positional call. |
| `checker/tests/test_aggregate_fold_version.py`, `test_rules_2_aggregates_fold_four_states` | `M3`, waits for the `rezono.rules/2` IR (`compiler/tests/test_functional_derivation_ir.py`) | Through `load_rules` and `recompute`, `sum`, `min` and `max` of a `rezono.rules/2` program give `not_applicable` over known and `not_applicable` cells, `unknown` over known and `unknown` cells, and `invalid` over known and `invalid` cells. |
| `checker/tests/test_aggregate_fold_version.py`, `test_rules_1_aggregates_keep_formal_6` | green guard | The same aggregates of a `rezono.rules/1` program skip `not_applicable`, are strict in `unknown` and block on `invalid`, as §6 of the formal foundations gives. |

## Considered

- **Keep the positional aggregate beside the tuple-set form.** Two spellings for one thing, which "One core, one way" excludes.
- **Remove the positional call altogether**, so that existence reads `line.any(application = a)`. It would reopen the token decision of 2026-11-19 for `_`, and a positional call reads well where it only tests a row, as the adopted `provides(it, f, _)` shows.
- **`W107` for the positional aggregate in `rezono 0`.** There is no replacement in `rezono 0` to name, and `rezono 0` has no external deprecation promise.
- **One strict fold for both formats.** It would change the results, and so the proofs, of existing `rezono.rules/1` publications without a change in their text.
- **A format argument that defaults to the `rezono 0` rule.** A caller that forgot it would skip `not_applicable` in a `rezono.rules/2` program without anyone noticing.
