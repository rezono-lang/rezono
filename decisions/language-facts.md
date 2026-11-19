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

The reader refuses a repeated key, which it sees in the cell itself. It does not refuse an unknown key: the embedded kind can come from another pack, so whether a key is one of its slots is known only after linking. The compiler refuses an unknown key when it decodes the record against the embedded kind. The reader does not refuse an unknown key even when the embedded kind is declared in the same module, so that the place of a declaration does not change what a module means.

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

## A dash in any fact table

A dash omits a slot in every fact table: a table on its own in a module and a table in a dataset read a dash the same way, as `{"boundary": "omitted"}`. A cell means the same wherever its table stands, and the compiler already decodes an omitted cell the same way in both, because it reads a module of fact tables as the named dataset of its file name. A dash never stands in the first column, which holds the row identity. In a source column a dash keeps its own meaning, the value of the source declaration.

```rezono
fact Host
  | id     | owner |
  | host-a | -     |
```

Allowing the dash only inside a dataset was considered. It would make the same row mean something in one place and be refused in another.
