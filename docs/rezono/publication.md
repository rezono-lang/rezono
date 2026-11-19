# Publishing a pack written in Rezono

This reference describes how the compiler lowers a Rezono module to the same schema bundle and rule intermediate representation (IR) used by other packs. [§5](#5-what-the-slice-lowers) describes the base design, and [§9.1](#91-a-decision-table-under-unique) specifies decision-table lowering. Reader and compiler support can differ. The compiler rejects a construct for which it has no lowering.

A **module** here is a file of the [Rezono language](v0.md#4-modules). A LinkML schema file is named explicitly where the distinction matters.

## 1. One publication pipeline

- **Lowering.** The compiler converts the module form into the schema bundle and [rule IR](../../contracts/rules.yaml), format `rezono.rules/1`. The engines, witness checker and publisher use the same interfaces for every pack. Soufflé can check the rule results, and the checker can verify their proofs.
- **Evaluation.** Publication runs the lowered rules in the existing engines. The Rezono evaluator answers `ask` queries separately.
- **Exact meaning.** A supported lowering preserves the meaning of the construct in all four value states. Unsupported forms fail with diagnostics before a publication is written.
- **Determinism.** The same module text gives the same JSON form. The same pack definition gives the same bundle and rule IR. Declarations and source origins are derived from the authored text.

## 2. The seam: the JSON form of a module

The language reader writes the [module JSON form](../../rezono/README.md#the-json-form-of-a-module). The compiler reads that form beside `schema/` and `rules/`. The [module form contract](../../contracts/rezono-module.yaml) defines its shape, including the `rezono.module/1` form used in the examples below.

- The form carries declarations in source order and expressions as trees. Lowering resolves the names it uses against the kinds and enums visible in the pack. A name that fails resolution is a diagnostic.
- The form records authored spans. Errors name the module and the line of the rejected construct. An error on a module header can use the line of the corresponding header word. Lowered facts and rules carry their authored source locations.
- An absent member means the text omitted it. A value written as `n/a`, `unknown` or `invalid` retains its explicit state in the form.
- A module requires the form named in the pack manifest. The reader emits a form only when it can read the complete module.

The [pack contract](../../contracts/pack.yaml) names each source, its form and the layer of its kinds under `rezono` in `pack.yaml`. Both paths are below `rezono/` in the pack.

```yaml
rezono:
  - module: rezono/assets.rezono
    form: rezono/assets.json
    layer: facts
```

The module's name is its path under `rezono/` without the extension. The compiler reads the form for lowering and uses the source for diagnostics. Undeclared module files are rejected. Both files contribute to the [pack's definition hash](../compiler/pack.md).

## 3. The pack around the modules

| Part of the pack | Where it is stated |
|---|---|
| Name, version, default language and imports | `pack.yaml`. Each module's `pack` line must name that pack. The language syntax for the name cannot spell a hyphen. |
| Kinds, slots and enums | Rezono modules or `schema/*.yaml`. A duplicate name within the closure is an error. A Rezono slot can refer to a schema kind or enum visible in the pack. A LinkML class resolves through LinkML imports, which do not include Rezono modules. |
| Layer of a kind | The manifest supplies the layer for the kinds of a Rezono module. Schema files supply the layer for their own classes. |
| Derived values and rules | Module declarations with a lowering and existing `rules/*.dl` modules. See [§5.4](#54-a-derived-truth-value). |
| Facts | Module fact tables and `facts/*.yaml` contribute to the pack's main state when supported. |
| Scenarios and diagnostics | `scenarios/*.yaml` and `diagnostics/*.yaml`. |
| Roles and read rules | The pack's `may_read` rules. |
| Channel table | `channels.yaml`. |
| Labels and sentences | `labels/<lang>.yaml` and `messages/<lang>.mf2`, keyed by element or message identifier. Module comments carry no labels or sentences. |
| Explanation questions | `questions.yaml` or a pack import. |

The module's `rezono 0` header is checked during lowering. The source header and the module form's format identifier are separate fields.

## 4. Value states

The four [language value states](v0.md#7b-truth-and-value-states) correspond to the following compiler states in this design.

| Rezono | Compiler | A slot in a closed kind | A lowered derived truth value |
|---|---|---|---|
| A known value | `known` | One row supplies the slot value. | The outcome row is `known`, with a row in the true or false relation. |
| `n/a` | `not_applicable` | An optional slot has no row. | The outcome row carries its reason. |
| `unknown` | `unknown` | A required slot has no row. The totality check records a violation. | The outcome row carries its reason. |
| `invalid` | `invalid` | A violation view has a row, for example for two values or an unresolved reference. | The violation blocks publication. |

1. **A result for each element.** A set-valued rule drops a binding with a missing premise. A derived value must record a state for each element of its kind. Its named outcome has exactly one row per element. An unknown or inapplicable value keeps its reason and proof on that row.
2. **Violations block publication.** The [expression truth tables](expressions.md#appendix-a-truth-tables-normative) give `false and invalid` as `false` and `true or invalid` as `true`. A violation of an input to a publication blocks it even if the expression could short-circuit over the invalid value.
3. **Version gaps and overlaps.** The [language's validity and applicability rules](v0.md) give `unknown no_version_applies` for a gap and `invalid versions_overlap` for an overlap that the rules cannot resolve. The base subset refuses versioned declarations.
4. **Explicit worlds.** This lowering needs the author to say `world closed` or `world open` on a root kind. The compiler's default for a schema relation does not select the world of a Rezono kind.
5. **Reason and cause.** A named outcome supplies a reason code for each non-known state. The pack renders it with `reason.<code>`. When a read found a missing slot, `no_value` is the reason and the missing fact row is the absent premise of the proof.

If a numeric lowering computes a result outside its representable range, it yields `unknown` with a reason. A numeric result is never substituted for it.

## 5. What the slice lowers

The base design covers kinds, slots, enums, fact tables and one derived truth value. The compiler currently lowers kinds, slots and enums in this subset. The fact table and Boolean expression below specify the base design for their lowering. The examples use an asset and its inspections.

### 5.1 Kinds and slots

```rezono
kind Asset world closed
  installed_on: Date?
kind Inspection world closed
  asset: Asset
  inspected_on: Date
```

These kinds lower to the same schema as the corresponding LinkML classes.

```yaml
Asset:
  attributes:
    id: {identifier: true}
    installed_on: {range: date}
Inspection:
  attributes:
    id: {identifier: true}
    asset: {range: Asset, required: true}
    inspected_on: {range: date, required: true}
```

- The compiler derives kind, slot and relation identifiers from their names. For example, `InspectionBatch` gives `inspection_batch`, with slot identifier `inspection_batch.inspected_on`.
- In this base form an element has a textual identifier supplied by its fact row. A slot `s: T` is required and `s: T?` is optional. A slot may refer to another kind, `Date`, `Text` or an enum.
- The compiler produces the ordinary kind and slot tables `k(id)` and `k__s(id, v)`, with the identification, totality, functionality, reference and range checks.
- In the `rezono.module/2` form, `world open` on a root kind lowers to the LinkML annotation `world: open` on its class, and `world open` on a slot to the same annotation on its attribute. `world closed` is the LinkML default and adds no annotation. A subkind has the world of its root kind, an identifier has the world of its kind, and every slot of an open kind is open. The base `rezono.module/1` form refuses an open kind and a slot world.
- For an element in a closed kind, one value is known. Zero values are `n/a` for an optional slot and unknown for a required slot. Two values in a single-valued slot or an arrow to a missing element are invalid.

### 5.2 Enums

`enum Condition = ready | service_due | retired` lowers to a LinkML enum with those permissible values in source order. The enum is `condition` and a value is identified as `condition.ready`. The states belong to a slot of that enum, and a known value must occur in its declared list. This lowering accepts closed enums.

### 5.3 Facts

```rezono
fact Asset
  | id      | installed_on |
  | asset-a | 2024-01-01   |
  | asset-b | n/a          |
```

The first column supplies the element identifier and each remaining column names a slot of the kind. The records join the main state and pass the same admission checks as `facts/*.yaml`.

| Slot | Cell | Lowered value |
|---|---|---|
| A kind | The id of an element, such as `asset-a` | A reference to that element |
| `Date` | A valid calendar date | The date |
| `Text` | A text literal | The text |
| An enum | A declared enum value | That value |
| Any `T?` | `n/a` | No row for that slot |

The base fact-table design rejects a missing required value, a path as a column, an explicit `unknown <reason>` or `invalid <reason>` cell and an attached source. Duplicate ids fail the identification check. Individual fact declarations with `valid` and `known` are a separate form.

### 5.4 A derived truth value

A derived truth value attaches a typed expression to an element. Authored rules have their own syntax and type checking in the [native rules design](../../decisions/language-native-rules.md). That design preserves the rule IR and witness requirements used by publication.

The base truth-value design uses `derived name: Bool = expression` in a kind or under `extend K`. A path evaluates to its last value when every step has a row. Otherwise it takes the state of the first missing step. The following expression illustrates a comparison whose language meaning is specified even where this lowering refuses date reads.

```rezono
extend Inspection
  derived recorded_after_installation: Bool =
      when asset.installed_on is n/a then false
      else asset.installed_on <= inspected_on
```

| Form | Meaning in the base design |
|---|---|
| `true`, `false` | The truth value |
| `p is known`, `p is n/a` | A state test always gives true or false. The base lowering design covers arrows, text slots and enum slots. |
| `not a`, `a and b`, `a or b`, `a => b`, `when c then a else b` | The [expression truth tables](expressions.md#appendix-a-truth-tables-normative) |
| A comparison of dates | Compare known dates, otherwise propagate the highest operand state. Date reads require a dedicated lowering. |

For a derived value `d` of kind `k`, the design generates a named outcome and two Boolean result relations.

| Value | Rows |
|---|---|
| True | `k_d(x, "known", "")` and `k_d_true(x)` |
| False | `k_d(x, "known", "")` and `k_d_false(x)` |
| `n/a` | `k_d(x, "not_applicable", "no_value")` |
| `unknown` | `k_d(x, "unknown", "no_value")`. A missing required input also fails totality. |
| `invalid` | The violation blocks publication. |

State tests and missing steps can use negation over lower strata of closed relations. A lowering may generate intermediate relations whose names, like the outcome and result names, must be free of collisions. The proof uses the fact rows read by the expression and the absent rows identified by state tests. A role needs full read access to the relations on which the result depends by negation.

The base rule lowering has no lowering for date comparisons or state tests on a path ending in a date. With just constants, state tests and connectives, a lowered expression produces true or false. The rows for `n/a` and unknown require a strict expression, such as a date comparison once it has lowering support. The [native-date equality decision](../../decisions/independent-date-equality.md) describes equality between independently recorded dates in the rule IR. It does not specify publication lowering for every Rezono date expression.

## 6. What is refused

The compiler rejects a construct with no supported lowering at its source location. A syntax error is reported by the language reader. A construct present in the form and unsupported for publication is reported by the compiler. The pack does not compile with part of a module omitted.

The base subset does not define publication lowering for parameter versions, unit arithmetic, rounding, exceptions with `unless`, checks, seals, time selection, inverse-slot aggregates or authored states on fact cells. The [language reference](v0.md) and the [public design decisions](../../decisions/) describe these constructs separately. A compiler extension can add a lowering without changing the meaning of the base subset.

## 7. Conformance

Compare the publication of a Rezono module to the publication of independently authored schema, facts and rules with the same meaning. Compare admitted rows, conclusions and states, and verify each witness against its own publication's source locations. A rejected form must report the expected source location. See the [semantic publication comparison](../../decisions/language-semantic-publication.md) and its [executable test](../../compiler/tests/rezono/test_semantic_publication.py).

## 8. Source and compiler responsibilities

The language reader owns reading, printing, the JSON form and syntax diagnostics. The compiler owns name resolution for lowering, generated schema and rules, source mapping, and diagnostics for unsupported constructs. Publication runs the generated program through the shared engine.

## 9. The constructs that follow

The following sections specify additional lowering forms and any restrictions specific to their publication.

### 9.1 A decision table under `unique`

[Decision-table semantics](tables.md#3-meaning) defines how to evaluate a table. This section specifies its lowering to a publication.

This lowering accepts an `extend K` with a `table unique` on each derived value. `K` is an unsealed closed kind of the same pack. An input is a single-valued enum or unitless integer slot on `K` or an ancestor. The output is an enum of the pack. A cell tests equality or a range of whole numbers, or uses the wildcard. Other policies, `total`, path or expression inputs, and an imported module's table are outside this lowering.

For a derived value `d` of kind `k`, let `P` be `<k>_<d>`.

| Relation | Rows |
|---|---|
| `P(k, state, reason)`, `// @outcome k` | One per element. An applying row gives `known`; an undecided row with none applying gives `unknown no_value`; no applicable or undecided row gives `unknown no_row_applies`. |
| `P_value(k, value)` | The output of each applying row. |
| `P_conflict(k, row, other)`, `// @invariant` | Two rows apply to the same element. This is `invalid exception_conflict` and blocks publication. |
| `P_row`, `P_cell`, `P_applies`; and for a tested required slot, `P_has`, `P_missing`, `P_false`, `P_open`, `P_undecided` | Intermediate relations for tests, applying rows and rows made undecided by a missing required value. |

A cell holds when its slot has a value that passes a test. A present value that passes none yields false. An absent optional value gives `n/a`; an absent required value gives unknown and also violates totality. A row applies when all its tested cells hold. A row is open if a required value is missing and none of its cells is false. This preserves the expression truth table for `n/a and unknown`. The generated rules read ordinary kind, enum and integer relations and negate only lower strata. Each rule carries the source location of the table part it lowers. Unknown outcomes have an explicit state and reason. The pack supplies the sentences `reason.no_value` and `reason.no_row_applies`.

Generated relation names must be free of collisions. The outcome row carries the cause of `no_row_applies`, since the derived value does not have a stored slot table.
