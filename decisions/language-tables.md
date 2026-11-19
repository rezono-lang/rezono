# Decision tables

Retain the existing table tree under the derived member. Preserve row order, policy, wildcard cells, open endpoints and ordered enum priorities. This fragment is the value of its table member. Lower via the table publication path. Sorting rows could change a first-match result.

```rezono
derived size: Text
  table first
    | large | -> size |
    | true | "big" |
```

The corresponding JSON fragment is

```json
{
  "table": "first",
  "inputs": [
    {
      "path": [
        "large"
      ]
    }
  ],
  "output": "size",
  "rows": [
    {
      "tests": [
        [
          {
            "lit": "true"
          }
        ]
      ],
      "value": {
        "lit": "\"big\""
      }
    }
  ]
}
```

## Lowering a first table

A `table first` lowers to the same two relations as a `table unique` ([publication.md section 9.1](../docs/rezono/publication.md#91-a-decision-table-under-unique)): the named outcome of the derived value, with its state and reason per element, and the relation of its known values. The value follows [tables.md section 3](../docs/rezono/tables.md#3-meaning) for `first`. A row that applies wins over every row below it, so two applying rows are no conflict and the table has no conflict invariant. An undecided row above the winning row makes the value undecided only when its output differs from the winning row's output.

## Lowering a priority table

A `table priority` lowers to the same two relations as a `table unique`: the named outcome of the derived value, with its state and reason per element, and the relation of its known values. The value follows [tables.md section 3](../docs/rezono/tables.md#3-meaning) for `priority`. Among the rows that apply, the output that comes first in the order of the output enum's values wins, whatever the order of the rows. Two applying rows are no conflict, so the table has no conflict invariant. An undecided row makes the value undecided only when its output comes before the winning output in that order. No row applies: the value takes the state of the undecided rows, else it is `unknown no_row_applies`, as for `first`.

## Lowering a collect table

A `table collect` gives a set, so its derived value is written with the type `T*` and its form has `"card": "*"` beside the output enum `T`. Its lowering keeps the shape of the other policies and adds one relation for the members whose membership is undecided. For a derived value `d` of kind `k`, with `P` the name `<k>_<d>`:

| Relation | Rows |
| --- | --- |
| `P(k, state, reason)`, `// @outcome k` | One per element, always `known` with an empty reason: a set is a value even when no row applies, and then it is empty ([tables.md section 3](../docs/rezono/tables.md#3-meaning)). |
| `P_value(k, value)` | The output of each row that applies, once per output: the known members. |
| `P_undecided_member(k, value, state, reason)` | Each output that undecided rows give and no applying row gives, once per output, with the highest state among those rows and the reason that Appendix A.4 of expressions.md picks among them. |

Two rows that apply are no conflict, and two rows with the same output give one member. The undecided state of a member stays on its membership and never on the outcome row of the set: a `count` or an `any` over the set reads it there, as expressions.md section 7 says for a member of a filter. In the slice of publication.md section 9.1 an undecided row comes from a missing required input, so the state is `unknown` and the reason `no_value`.

### Considered

- **The outcome row of the set takes the state of its undecided members.** Then a set with one known member and one undecided member would have no known value at all, and a reader could not tell it from a set of which nothing is known.
- **One member relation with a state on every row, known members included.** The known members would then live in another relation than the known values of every other policy, and a reader of `P_value` would need to know the policy.
