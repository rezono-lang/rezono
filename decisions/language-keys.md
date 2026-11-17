# Composite keys and path equality

Attach named keys to a kind in its keys array. A sibling 'equal name = a.b, c' in equations encodes name as equal and its two ordered segment arrays as left and right. Preserve names when lowering to unique keys and path equations. Anonymous checks would lose the identity reported with a violation.

```rezono
unique pair = left, right
```

The corresponding JSON fragment is

```json
{
  "unique": "pair",
  "slots": [
    "left",
    "right"
  ]
}
```
