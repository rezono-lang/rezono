# Structured and sparse fact cells

Extend the existing fact table cell with lists and embedded records. The fragment is the second cell. Record keys map to cells under record. A dash is an omitted slot, encoded as {boundary: omitted} with both words as strings. Unknown, n/a, an empty list, and an absent value are distinct. Preserve source order, row identity, named datasets and versioned assignments. 'dataset name' encloses fact declarations and adds a dataset name and a decls array. Flattening nested data would change publications.

```rezono
fact Shelf
  | id | names |
  | s1 | ["East","West"] |
```

The corresponding JSON fragment is

```json
{
  "list": [
    {
      "lit": "\"East\""
    },
    {
      "lit": "\"West\""
    }
  ]
}
```
