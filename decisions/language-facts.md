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

## Writing a record cell

Write an embedded record as braces around `slot: cell` pairs separated by commas, in the order of the embedded kind's slots: `{street: "Oostweg 5", city: "Middelburg"}`. A key is a slot name of the embedded kind; each value is an ordinary cell, so a record may hold lists, records and a dash. A repeated or unknown key is refused. An empty list is `[]`; a dash in place of the whole cell omits the slot.

```rezono
fact Branch
  | code | address |
  | oost | {street: "Oostweg 5", city: "Middelburg"} |
```

The cell's JSON fragment is

```json
{
  "record": {
    "street": {"lit": "\"Oostweg 5\""},
    "city": {"lit": "\"Middelburg\""}
  }
}
```

Braces and `key: value` follow the metadata objects of annotations and the slot declaration form. A positional tuple was considered; it would break when the embedded kind gains a slot.
