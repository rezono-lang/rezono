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
