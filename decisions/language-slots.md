# Slot types and constraints

Use the existing slot and cardinality suffix. A deeper line constrains that slot. 'minimum n', 'maximum n', and 'pattern s' contribute single-key constraint objects with decimal or text strings. Boundaries are inclusive. Preserve optionality separately from numeric bounds. Named scalar aliases use 'type Cents = Int' and a declaration with type and base members. Mapping all aliases to Int would lose their schema identities.

```rezono
authors: Text*
  cardinality 1..3
```

The corresponding JSON fragment is

```json
{
  "slot": "authors",
  "type": "Text",
  "card": "*",
  "constraints": [
    {
      "cardinality": [
        "1",
        "3"
      ]
    }
  ]
}
```
