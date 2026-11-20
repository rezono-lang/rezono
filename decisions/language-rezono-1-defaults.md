---
decider: [language]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: language-rezono-1-defaults
---

# Close kinds by default in Rezono 1, guard observed kinds, and keep both precedence rules

[Rezono 1](language-rezono-1.md) is the first released language. Before packs convert to it, this decision settles seven of its defaults. Two change the language: a kind without a world line is closed, and a kind whose rows are observed must say `world open`, closed only within a scope it names with `complete by`. One adds a warning. Four keep what exists and say why, so the language guide can explain them. Nothing here changes the meaning of a `rezono 0` text ([language reference §4b](../docs/rezono/v0.md#4b-language-version-and-deprecation)).

| Point | Outcome in `rezono 1` | What changes |
|---|---|---|
| 1. The world of a kind without a world line | `closed`; `open` stays the default in `rezono 0` | the compiler lowers by version; the form does not change |
| 2. A kind whose rows are observed | `world open`, optionally `complete by <relation>`; otherwise R051 | a new refusal, a new kind clause and the core reason `incomplete_read` |
| 3. `world closed` written on a kind | W107, hint "leave it out" | a new warning |
| 4. The LinkML boundary | an optional slot becomes `T?`; an open class becomes `world open` | a conversion rule |
| 5. Precedence of `unless` and `table first` | unchanged: a later `unless` wins, the first applying row wins | the language guide |
| 6. Several values from `.one()` | unchanged: an `invalid multiple_values` finding | the language guide |
| 7. A file without a `rezono` line | unchanged: R028 in a `rezono 1` pack | nothing |

## 1. Kinds are closed by default in `rezono 1`

In a `rezono 1` module, a kind without a `world` line is closed: a missing row is false as a membership proposition. `world open` is the one way to open a kind. In `rezono 0` the default stays `open`, as [v0 §5](../docs/rezono/v0.md#kinds-and-slots) and the "Worlds" bullet of [readable rules](language-readable-rules.md#1-a-shorter-header) give it.

The reasons:

- **The packs already say it.** At `a29bb9e`, 147 of the 150 kinds in tracked `.rezono` files write `world closed`. Two of the other three write `world open` (`IncomeStatement` in `examples/subsidy-scheme/candidate/subsidy.rezono` and `Team` in `rezono/test/module.rezono`); the third is a subkind with the world of its root kind (`EvaluationDay is ReferenceDate`). No module relies on the open default: the compiler refuses a kind without a world line ([`rezono_kind.py`](../compiler/rezono_compiler/rezono_kind.py), "an open kind is refused: a kind says `world closed`").
- **The two input forms agree.** A LinkML class without a world annotation is closed ([the default world for a LinkML kind](conformance-value-world-default.md)). A native declaration with the open default was the one place where the same model meant something else depending on how it was written.
- **Functional derivations need it.** Every functional derivation in `rezono 1` needs a finite closed domain ([Rezono 1 §2](language-rezono-1.md#2-one-derivation-form-derived)). With an open default, every single-key derived value on a kind without a world line would be refused with `functional_open_domain`.
- **Enums already work this way.** An enum is closed unless it says `enum Name world open = …` ([v0 §4c](../docs/rezono/v0.md#4c-public-surface-and-compatibility)). Kinds now follow the same rule.

What follows from it:

- **Subkinds.** A kind with a parent has the world of its root kind and writes no world line, as today.
- **Slots.** v0 §5 gives a world per kind or per slot, but does not say how the two relate. The compiler does, and that stays ([`pack.py`](../compiler/rezono_compiler/pack.py), [`rezono_slot.py`](../compiler/rezono_compiler/rezono_slot.py)): a slot without a world line has the world of its kind; every slot of an open kind is open, so `world closed` on one is refused; an identifier has the world of its kind. `world open` on a slot of a closed kind keeps working. [`std-decision`](../packs/std-decision/candidate/decision.rezono) shows why: `kind Decision` is closed, and `decider: Text* world open` says that a record without a decider does not mean that nobody decided.
- **The form stays as written.** As in [readable rules §1](language-readable-rules.md#1-a-shorter-header), the reader never writes the default into the module form. A kind without a world line has no `world` member in `rezono.module/5`; a kind that writes `world closed` keeps the member as written. The bytes of every form, and so every pack hash, stay as they are ([definition hash coverage](pack-hash-coverage.md)).
- **One lowering.** The compiler applies the default once, when it lowers a form, by the module's version: an absent kind world is `open` in `rezono.module/1` to `/4`, where the compiler refuses it as today, and `closed` in `rezono.module/5`. A closed kind lowers to a LinkML class without a `world` annotation, so a `rezono 1` kind without the line and the same kind with `world closed` lower to the same schema, byte for byte. Every other reader that builds a schema from a module form, such as an example runner in `rezono/src/`, applies the same rule.
- **No published world changes.** Every lowered `rezono 0` kind states its world, and the conversion keeps each world (section 4). Moving a pack to `rezono 1` therefore closes no open world; it is not the major change "close an open world" of v0 §4c.

## 2. An observed kind is open, and closed only within a scope it names

A closed default must not let observed data be read as complete by accident: unknown stays explicit ([AGENTS.md](../AGENTS.md), rule 4). In a `rezono 1` module, an **observed kind** declares `world open`. Where completeness is shown, it adds the scope in which it is closed: `world open, complete by <relation>`. Otherwise the compiler refuses it with **R051** at its kind line, naming the kind. Writing `world closed` does not satisfy the guard: it only repeats the default (section 3).

- **Which kinds are observed.** A kind whose rows come from observations or from another party's records: a measurement, a reported status, a register, an export, the ledger of another system ([observation contract](../contracts/observation.yaml); a reference source in [AGENTS.md](../AGENTS.md), rule 6). The compiler knows this from the layer: v0 §5d calls it the source class `observation`, and [`contracts/pack.yaml`](../contracts/pack.yaml) gives each module registration a `layer`, one of which is `observation` (`LAYERS` in `pack.py`). The layer is the pack's declaration of where a kind's rows come from. The source of a row ([`contracts/source.yaml`](../contracts/source.yaml): `query`, `tool`, `person`, `document`, `third_party`) describes that row at publication, not the kind when it compiles, so the guard reads the layer. A definition that reads an observed kind has the effect class `reads` (v0 §5d).
- **The code.** R051 is the next code after the registers in the repository: R001 to R034 in v0 §10, R035 to R037 in `rezono/messages/`, R040 to R049 in [native rules §6](language-native-rules.md#6-diagnostics) and R050 in [calculated values](language-calculations.md). R038 and R039 have never been assigned and are left alone. R051 refuses an observed kind that is neither `world open` nor `complete by` a scope; since `complete by` follows `world open`, that is a kind without `world open`. The English sentence is "`{0}` is observed: declare `world open`, and `complete by` the scope in which it is complete"; its English and Dutch templates go into `rezono/messages/`, as native rules §6 asks of every new code.

What the guard keeps true, in four examples from the repository:

| Kind | Its rows | In `rezono 1` | What stays explicit |
|---|---|---|---|
| `IncomeStatement` ([subsidy scheme](../examples/subsidy-scheme/candidate/subsidy.rezono)) | the income register's statement | `world open`, as it is written today | H003 has no statement, so the income for A003 is unknown: its assessment stays `unknown income_statement_not_received` and its award unknown, never computed from an income of zero ([subsidy](../examples/subsidy/README.md)) |
| `CmdbObservation` ([CMDB reference](../examples/platform/schema/cmdb_reference/inventory.yaml)) | another party's inventory export | `world open, complete by` its scope relation (below) | a service missing from the export is a finding inside the scope and `unknown incomplete_read` outside it ([CMDB scope](platform-cmdb-scope.md)) |
| `HealthProbe` ([management health](../examples/platform/schema/management_health.yaml)) | a probe's reading | `world open` | a missing or undated reading leaves the health step unknown |
| `Decision.decider` ([`std-decision`](../packs/std-decision/candidate/decision.rezono)) | a slot of the pack's own record | the kind is closed, the slot `decider: Text* world open` | `in_force_without_decider` stays an `@absence` finding: somebody decided, and the record does not say who |

`CmdbObservation` and `HealthProbe` are LinkML classes in a `facts` layer today, closed, and their rules read the scope or the reading's time to keep the absence explicit. When they convert, they move to an `observation` layer: the CMDB export names its scope with `complete by`, the probes stay plainly open, and any result that changes is listed as section 4 says.

### The scope: `complete by`

```rezono
kind CmdbObservation world open, complete by in_scope
  export: CmdbExport
  service: Text
  cluster: Text

derived in_scope(export: CmdbExport, service: Text): Bool = CmdbScope.any(it.export = export and it.service = service)
```

- **Spelling.** On the kind line of a `rezono 1` module, after `world open`: a comma, `complete by` and the name of a relation. The reader reads the name into the kind's form member `complete`, beside `"world": "open"`, and prints the line back as `kind <K> world open, complete by <relation>`. It resolves no name, as for every declaration. Without `world open` before it, `complete by` is R000: a closed kind needs no scope. A subkind has the completeness of its root kind, as it has its world.
- **The relation.** `<relation>` is a `Bool` relation whose key binds the scope: a `derived …: Bool` of the pack, as above over the CMDB scope rows ([CMDB scope](platform-cmdb-scope.md)); a covered sweep of `std-loop` (`covered_sweep_node`, [complete sweep](../packs/std-loop/rules/complete_sweep.dl)); or a relation derived from the protected `verified_receipt` ([scoped completeness §2](scoped-completeness.md#2-shared-rule-interface)). Each of its columns is named after a slot of the kind, the identifier included, and has that slot's type; a row of the kind falls in the scope when its values in those slots form a key for which the relation holds. The compiler refuses a relation that is not `Bool`, or a column that names no slot of the kind, with R003 at the relation's name.
- **Inside the scope the kind is closed.** For a key where `<relation>` holds, a missing row of the kind is false. Negation, aggregation and `.one()` over the kind are admitted when the expression binds every column of `<relation>`; otherwise the kind is open there and R004 applies, as for any open kind. The coverage row is a positive premise of every witness that relies on the closed reading, so the independent checker checks it with the absence it supports, and a role that reads the conclusion must read the coverage row ([witnessed read completeness](witnessed-read-completeness.md)).
- **Outside the scope the kind stays open.** For a key where `<relation>` does not hold, a missing row is `unknown` with the new core reason **`incomplete_read`**: the read that would show the absence is not known to be complete for that key. `contracts/value.yaml` has no such code (its core codes are `no_version_applies`, `versions_overlap`, `exception_conflict`, `no_row_applies`, `ambiguous_date`, `empty` and `added_later`). `incomplete_read` labels `unknown` only, and enters `contracts/value.yaml`, [publication L0 §2.3](../docs/publication/l0.md#23-reasons) and `CORE_REASONS` in `publication/rezono_publication/l0.py`, as `no_match` does in [Rezono 1 §2](language-rezono-1.md#2-one-derivation-form-derived). The evaluation reason `open_world` ([expressions §7](../docs/rezono/expressions.md)) keeps labelling a kind without `complete by`: there no scope could be widened, so its remedy differs.
- **Receipts and epochs.** A relation derived from `verified_receipt` holds only for receipts that admission verified in that epoch ([admission transport](admission-transport.md)). In an epoch without an admitted receipt it is empty, so every key lies outside the scope. A receipt therefore never closes the kind as such: it closes it within its scope, at its cut, in its epoch.
- **Functional domains.** A functional derivation that reads the kind declares `over <relation>(…)`, so its domain is the covered keys, a closed `Bool` relation as [Rezono 1 §2](language-rezono-1.md#2-one-derivation-form-derived) asks. A key outside the scope is outside the domain and has no row. A question that reads the derivation for such a key gets `unknown incomplete_read`, never `known`, also in an epoch whose coverage relation is empty.

## 3. `world closed` on a kind in `rezono 1` gives W107

A kind line in a `rezono 1` module that writes `world closed` gives **W107** at the words `world closed`, with the hint "leave it out" (`hint.leave_out`), as a header line that writes its default does in [readable rules §1](language-readable-rules.md#1-a-shorter-header). The module still reads. Its form keeps `"world": "closed"` as written and prints it back, so the form, its bytes and the pack hash do not change, and the kind means what it means without the line.

- `world open` on a kind gives no warning: it deviates from the default. In `rezono 0`, `world closed` is not the default and gives no warning.
- This is the deprecated phase of v0 §4b in `rezono 1`: W107 at every use, meaning unchanged. A later language version may remove the line (R028). The header lines of readable rules are a phase further: they were deprecated in `rezono 0` and are R028 in `rezono 1`. `world closed` on a kind was not a default before `rezono 1`, so it starts at W107.
- A slot line that writes `world closed` gets no warning from this decision.
- Reader tests whose `rezono 1` sources expect no diagnostic do not write the line. `rezono/test/test_rezono_1_version_switch.py`, `test_rezono_1_derived.py` and `test_rezono_1_literals.py` leave it out with their expectations unchanged; `test_rezono_1_examples.py` keeps it until its example runner reads an absent world as closed (Order, below).

## 4. The LinkML boundary keeps each slot's meaning

The one-time conversion of a pack to `rezono 1` ([Rezono 1 §6](language-rezono-1.md#6-single-pass-rule-conversion-and-readiness-gate)) keeps the meaning of every slot and every world. In Rezono, `T` is required and a missing value is `unknown`, while `T?` is optional and a missing value is `n/a` (v0 §5). A LinkML slot is optional unless it says `required: true`. A conversion that wrote `T` for every LinkML slot would turn each missing optional value from `not_applicable` into `unknown`.

| LinkML | `rezono 1` |
|---|---|
| `required: true` | `T` |
| neither `required` nor `multivalued` | `T?` |
| `multivalued: true` | `T*`, or `T+` with `required: true` |
| a class without a world annotation | a kind without a world line, which is closed |
| a class with `annotations: {world: open}` | `world open` |
| a slot with `annotations: {world: open}` | the slot with `world open` |
| the `layer` of the schema or of the class | the `layer` of the module's registration in `pack.yaml` |

[`scripts/convert_pack.py`](../scripts/convert_pack.py) already maps cardinality this way; for `rezono 1` it leaves out `world closed` on a kind (section 3).

This is a conversion rule, not an intended difference. It stands beside the tables of [Rezono 1 §5.5](language-rezono-1.md#5-cross-module-readers-acceptance-tests-oraclepy-and-the-external-reader-contract) and [§7](language-rezono-1.md#7-per-derivation-intended-semantic-differences-for-examplesplatformrulescoredl): the whole-pack equivalence test treats a changed value state caused by converting a slot or a world as a test error, as §7 treats every difference it does not list.

One case cannot keep its meaning: a closed class whose rows are observed. Today these are the classes of `examples/subsidy/schema/reference.yaml` and `examples/subsidy/schema/credentials.yaml`, one class of `examples/library/schema/library.yaml` (all in an `observation` layer), and the observed classes of the platform example in section 2. Converted as closed, such a class meets R051. The conversion stops at it and names it. The pack then writes `world open, complete by` the scope in which its rows are complete, or opens it without a scope; either way it lists every result that changes as an intended difference, in the form of Rezono 1 §7.

## 5. Precedence stays as it is

Rezono has two ordered forms, and they read in opposite directions on purpose. Neither changes; the language guide explains both.

- **An `unless` chain is a default with exceptions.** Each `unless` block overrides the base value and every block above it, so a later clause wins: it is an exception to the exception ([v0 §5](../docs/rezono/v0.md#derived-values-and-rules), [§5b](../docs/rezono/v0.md#5b-exceptions)). This is how a rule and its exceptions are written in law and policy: the general case first, the most specific case last, and an amendment adds a line at the end without touching what is above it. The proof of a value names the clause that fired and shows that the later clauses did not apply.
- **`table first` is an ordered list of cases.** The first applying row wins ([v0 §5c](../docs/rezono/v0.md#5c-decision-tables)). A table is read from the top, like the first hit policy of a decision table: the specific rows first and a row of `-` last, which catches the rest. W112 reports an input that no row covers.
- **Why both.** They answer different needs: `unless` refines one value under conditions, a table assigns a value per combination of inputs. Each puts its most specific case where its reader looks for it: at the end of a chain of exceptions, at the top of a list of cases. Turning either around would put the catch-all where the most specific case is expected, and would change the meaning of every valid text that uses it (v0 §1, goal 6). Rezono 1 keeps both ([Rezono 1 §1](language-rezono-1.md#1-fixed-invariants-and-scope)).

The language guide ([`rezono/README.md`](../rezono/README.md)) shows the two side by side, with the same outcome for known inputs:

```rezono
extend Offer
  derived discount_rate: Ratio = 10 %
    unless preferred then 20 %
    unless ineligible then 0 %          -- the last applying exception wins

extend Offer
  derived discount_rate: Ratio
    table first
      | ineligible | preferred | -> discount_rate |
      | true       | -         | 0 %              |
      | -          | true      | 20 %             |
      | -          | -         | 10 %             |
```

## 6. Several values from `.one()` stay a finding

`.one()` over two or more distinct values gives `invalid multiple_values`, with every candidate and its proof as witness, and publishes as a finding by default rather than blocking ([Rezono 1 §2](language-rezono-1.md#2-one-derivation-form-derived), publication conflict policy). Two records that disagree are a fact about the input that a reader should see with both sides; one such pair should not stop a whole epoch. A contradiction in the rules themselves (overlapping versions, sibling `unless` clauses that both apply, overlapping `table unique` rows) still blocks.

The language guide shows this with an example, such as two `Choice` rows for one `(a, f)` that make `needs(a, f)` invalid while `flow` derives nothing for that need. It also shows how a pack makes the conflict block: with a `check` or `require`, such as `check unique_provider: not (needs(a, f) is invalid)`, or by declaring the derivation `total`.

## 7. A missing `rezono` line

A file without a `rezono` line is read as `rezono 0` with W106; in a pack on `rezono 1` or later it is R028 ([v0 §4b](../docs/rezono/v0.md#4b-language-version-and-deprecation), [Rezono 1 §5.8](language-rezono-1.md#8-module-format-version-is-rezonomodule5)). The reader and the compiler tests of the version switch cover it. Nothing changes.

## Tests

| Test | What it expects | Mark |
|---|---|---|
| `compiler/tests/rezono/test_rezono_1_world_default.py::test_rezono_0_kind_without_world_stays_open` | a `rezono 0` kind without a world line is never lowered as closed; with `world closed` it lowers closed | green |
| `compiler/tests/rezono/test_rezono_1_world_default.py::test_rezono_1_kind_without_world_lowers_closed` | section 1: closed without the line, `world open` kept on a kind and a slot, a slot with its kind's world, the written line lowered byte for byte the same | `M3`, waits for the compiler version switch |
| `compiler/tests/rezono/test_rezono_1_world_default.py::test_rezono_1_observed_kind_needs_open_world` | section 2: R051 names each kind of an `observation` module without `world open`, also with `world closed` written; the same kind in a `facts` module is closed | `M3`, waits for the default |
| `rezono/test/test_rezono_1_world_line.py::test_rezono_1_world_closed_gives_w107` | section 3: W107 with "leave it out" at `world closed`, the form and its print as written, no warning without the line, for `world open` or in `rezono 0` | `M3`, waits for the default and the examples test |
| `rezono/test/test_rezono_1_complete_by.py::test_rezono_1_complete_by_reads_into_the_form` | section 2: `world open, complete by <relation>` reads into the members `world` and `complete` and prints back as written; `complete by` without `world open` before it is R000 | `M3` |

Specified here and not tested: what the compiler and the checker do with `complete by` (the relation's columns and R003, the closed reading inside the scope with its coverage premise, `unknown incomplete_read` outside it, the functional domain `over <relation>(…)`), the conversion rule of section 4 (it runs with the conversion), and the language guide examples of sections 5 and 6. Those tests need module-level `derived` relations, which the reader does not read yet (`rezono/test/test_rezono_1_derived.py`).

## Order

1. The default of section 1, in the compiler and in every reader in `rezono/src/` that builds a schema from a module form.
2. The guard of section 2 and the reading of `complete by`; then its lowering, the core reason `incomplete_read` and the checker's coverage premise, before a pack converts a kind that is observed and closed.
3. The warning of section 3. Before it lands, a planner removes `world closed` from the `rezono 1` source of `rezono/test/test_rezono_1_examples.py`, which expects no diagnostic, once that test is green and its runner reads the default of section 1.

## Considered

- **Keep the open default and require a world line on every kind.** That is the compiler's behaviour in `rezono 0`. Rejected: 147 of 150 kinds write the same two words, the LinkML input means the opposite, and functional derivations need the closed case.
- **A closed default without a guard.** Rejected: an observed kind without a world line would read a missing observation as false, and unknown would no longer be explicit.
- **Recognize observed kinds by the sources of their rows.** Rejected: a source describes one row when it is published; a theory pack declares kinds and has no rows. The layer is known when the pack compiles.
- **Let a receipt close an observed kind as such.** Rejected: a receipt covers one scope at one cut; the same kind in another epoch, or outside the scope, is not complete.
- **Name the scope in `pack.yaml` beside the layer.** Rejected: the scope is a relation with a key, which the rules already read; written on the kind line, it stands where a reader looks for the kind's world.
- **`complete by` on a closed kind.** Rejected: a closed kind is complete everywhere, so a scope would say nothing; the clause follows `world open`.
- **`open_world` outside the scope.** Rejected: outside a declared scope the remedy is to widen the scope or admit a receipt, so the reason names it (`incomplete_read`).
- **R028 for `world closed` in `rezono 1`.** Rejected: v0 §4b deprecates before it removes, and the line was never a default before `rezono 1`.
- **Write the default into the form.** Rejected, as in readable rules: every form, and every pack hash, would change without a change of meaning.
- **One direction for `unless` and `table first`.** Rejected in section 5.
- **Block on `.one()` conflicts by default.** Rejected in section 6: a pack that wants it says so with `check`, `require` or `total`.
