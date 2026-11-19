# Calculated values

Retain the derived expression tree and the existing version, valid, known and source members. Named outputs in a legacy calculation use 'output relation.slot' under the derived declaration, stored as output with relation and slot. Ordered, named definitions use 'definition name when condition then expression', stored under definitions as name, when and value. An explicit output prevents guessing a relation from a display name.

```rezono
derived doubled: Int = count * 2
```

The corresponding JSON fragment is

```json
{
  "derived": "doubled",
  "type": "Int",
  "value": {
    "arith": [
      "*",
      {
        "path": [
          "count"
        ]
      },
      {
        "lit": "2"
      }
    ]
  }
}
```

## Lowering to the calculation model

A calculation written in Rezono lowers to the same `rezono.calc/1` program that a `calc/*.yaml` file states today ([calculation contract](../contracts/calc.yaml)). The compiler then binds, checks and publishes it unchanged: the lowered program joins the pack closure exactly where a `calc/*.yaml` document would. The calculation files of `examples/subsidy-scheme` and `examples/subsidy` are the oracle. Their Rezono form must give the same bound program, `ir/calc.json`, and the same values, states and witnesses.

### Versions with definitions

A `version` line without `= value` opens a block. The block holds the definitions of that version. A version line with `= value` keeps its existing meaning: one definition, which applies always.

```rezono
extend Application
  derived cost_share: Int
    output cost_share.cents
    unit cents
    version 2026, valid 2026-01-01..<2027-01-01, known 2025-12-09
      definition full_rate when assessed_income.cents <= income_threshold
        then round(assessed_costs.cents * full_rate / 1000000)
      definition above_the_limit when income_limit < assessed_income.cents then 0
```

The JSON form keeps `versions` as a list. A version with definitions stores them under `definitions` in the version object, with the same `name`, `when` and `value` members as the definitions directly under a derived value:

```json
{
  "derived": "cost_share",
  "type": "Int",
  "output": {"relation": "cost_share", "slot": "cents"},
  "unit": "cents",
  "versions": [
    {
      "version": "2026",
      "valid": ["2026-01-01", "2027-01-01"],
      "known": "2025-12-09",
      "definitions": [
        {"name": "full_rate", "when": {"cmp": ["<=", {"path": ["assessed_income", "cents"]}, {"path": ["income_threshold"]}]}, "value": {"call": ["round", [{"arith": ["/", {"arith": ["*", {"path": ["assessed_costs", "cents"]}, {"path": ["full_rate"]}]}, {"lit": "1000000"}]}]]}},
        {"name": "above_the_limit", "when": {"cmp": ["<", {"path": ["income_limit"]}, {"path": ["assessed_income", "cents"]}]}, "value": {"lit": "0"}}
      ]
    }
  ]
}
```

The expression nodes are those the reader already writes for questions and derived values. The fragment shows their shape; the reader's existing node names decide where they differ. A derived value has either definitions directly under it or versions, never both (`R050`, `definitions beside versions`). A definition line may end in `overrides NAME because "reason"`, repeated, stored as `overrides: [{definition, reason}]`. It goes before the named definition of the same version.

`unit TEXT` under a derived value is stored as `unit`. It is required for lowering unless the declared type names a unit the pack declares, in which case that unit is used.

### What each member becomes

| Rezono | `rezono.calc/1` |
| --- | --- |
| The module's pack | `pack` |
| The kind of the enclosing `kind` or `extend` block | `subject`, as the kind's element id (`Application` gives `application`). All derived values that one module lowers share one subject (`R050`, `two subjects`). |
| `derived name` | `rule: name`. Each version gives one rule entry with `id: name@version`. |
| `output relation.slot` | `output: relation.slot` |
| `unit` | `unit` |
| `version V, valid A..<B, known K` | `version: "V"`, `valid_from: A`, `valid_until: B`, `known_from: K` |
| A derived value without a version line | One version `1`, valid from `0001-01-01` until `9999-12-31`, known from `0001-01-01` |
| `= expression` | One definition named after the derived value, with `when: {boolean: true}` |
| `definition n when c then v` | `{name: n, when: c, value: v}`, in written order |
| `overrides m because "r"` | `overrides: [{definition: name@version#m, reason: r}]` |
| `as of DAY known DAY` | `as_of: {valid_at, known_at}`. A module with only this line lowers to a program with no rules, whose subject is the one subject of the calculations in the pack closure. |

The bound program does not depend on the order of declarations in a module, only on the order of definitions within a version.

### Leaves

A path in a calculation resolves against the subject kind, in this order of kinds of name. More than one match is ambiguous (`R050`, `ambiguous leaf`); the author writes the full path.

| Path | Leaf |
| --- | --- |
| `p`, where `p` is a parameter in scope | `{parameter: p}` |
| `r`, where `r` is another derived value of the same subject in the pack closure | `{rule: r}` |
| `Kind.r`, where `Kind` is the subject kind and `r` another derived value of it | `{rule: r}`. This is the full path of a derived value whose name is also a parameter. |
| `s`, a slot of the subject kind | `{fact: subject.s}` |
| `rel.col`, where `rel` is a relation whose first column has the subject kind and `col` is another column | `{fact: rel.col}` |
| `rel`, a relation whose only column has the subject kind | `{fact: rel}`, read as presence: true when the subject has a row |
| An integer literal | `{integer: "N"}` |
| `true`, `false` | `{boolean: true}`, `{boolean: false}` |
| An integer quantity literal in a declared unit | `{integer: "N", unit: U}` |

A derived value never reads itself, so inside `derived r` the bare name `r` can only be a parameter or a fact. For example, `examples/subsidy-scheme` has a parameter and a derived value both named `advice_allowance`: the derived value reads the parameter as `advice_allowance`, and `entitlement` reads the derived value as `Application.advice_allowance`. The parameter's name cannot change, because it is the `name` of its rows.

A relation read like a slot is a calculation's existing column and presence reading. The compiler still decides how a fact is read (attribute, optional, column, presence), as it does for `calc/*.yaml`. A decimal or percentage literal lowers to an exact `ratio` of integers. For example, `13.7 %` gives `ratio(137, 1, 1000)`.

### Operators

| Rezono | Operator |
| --- | --- |
| `a + b`, `a - b` | `add [a, b]`, `sub [a, b]`; nested as written, never flattened |
| `x * n / d` | `ratio [x, n, d]` |
| `x * n` | `ratio [x, n, 1]` |
| `x / d` | `ratio [x, 1, d]` |
| `round(e)`, `floor(e)`, `ceil(e)`, `pow(b, e)`, `min(a, …)`, `max(a, …)` | The operator of the same name |
| `when c then a else b` | `if [c, a, b]` |
| `a and b`, `a or b` | `and`, `or` with the operand list of the tree |
| `a = b`, `a < b`, `a <= b`, `a >= b` | `eq`, `lt`, `lte`, `gte` with operands in written order |
| `a > b` | `lt [b, a]` |
| `not c` | `if [c, false, true]` |
| `a != b` | `if [eq [a, b], false, true]` |

These lowerings keep the strict state semantics of the calculation operators. `if` propagates the state of its condition, as `when` does. A product is not divided implicitly. `a * b / c / d` lowers its inner part to `ratio` and divides the result again, as written.

### Parameters

A row-backed parameter, `param name: T from Kind.slot by nameSlot`, lowers to the program members `parameters: kind.slot` and `parameter_choice: {name: nameSlot}`. Kind and slot use element ids. Validity and knowledge come from the kind's temporal slot roles, the short form of `parameter_choice`. A leaf `{parameter: name}` reads the row whose `nameSlot` equals the written name. The written name is therefore the parameter's one name, and no label file is needed. All row-backed parameters that one program reads share one source (`R050`, `two parameter sources`).

A parameter with inline versions or an inline value has no place in `rezono.calc/1`, which reads parameters as rows. Lowering such a calculation reports `R050` with `inline parameter` until a decision says how inline parameter versions become rows. Reading and the question evaluator keep supporting them.

### Refused

The following constructs report `R050` with the construct's name at its span: `unless` under a calculated value (see [ordered exceptions](language-exceptions.md)), a decision table, `is known` and the other state tests, set and aggregate expressions, `templates`, `inputs`, and a `rule@version` leaf. The calculation model has no operator for them, or the corpus does not use them. A later decision can add each one.

## Considered

- **Keeping `calc/*.yaml` beside the language.** That keeps two hand-written forms of one regulation. The track requires one.
- **Inferring the subject from the output relation.** The output can name any relation, and the explicit `extend` block already names the kind.
- **Flattening `+` chains into one n-ary `add`.** Both forms have the same value. Lowering exactly as written keeps the round trip between source and program trivial to check.
- **A `gt` operator.** The contract has none. Swapping the operands of `<` keeps the contract unchanged.
- **Substituting parameter values into the definition.** The valid and known axes must select rows independently on the evaluation date, so the leaf keeps the name.

## Tests that follow

The red tests per building block are planned separately. Each one compares with the existing files:

- reading a version block with definitions, `unit` and `overrides`, from the JSON form above;
- lowering `examples/subsidy-scheme/calc/award.yaml` and `examples/subsidy/calc/drift.yaml` and `date.yaml` from hand-written Rezono, comparing the bound `ir/calc.json` with the one the YAML gives;
- lowering a row-backed parameter to `parameters` and `parameter_choice`, with a counter-case of two parameter sources;
- each `R050` refusal at its span.

They are `rezono/test/test_calculation_versions.py`, `compiler/tests/rezono/test_lower_calculation.py` and `compiler/tests/rezono/test_lower_parameters.py`.
