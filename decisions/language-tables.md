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
