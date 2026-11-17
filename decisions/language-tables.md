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
