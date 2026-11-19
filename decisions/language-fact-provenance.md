# Fact provenance

A fact table names where its rows come from. Write the shared fields once in a `source` declaration, and cite it after the kind of a fact table with `@`. A column whose header starts with `@` gives a source field per row. This replaces the `.sources.yaml` sidecar of a fact file with the same records, defaults and validation.

```rezono
source notices
  kind tool
  name "Release notice inspection"
  position "L1"

fact Notice @ notices
  | id     | holder  | @ revision | @ fragment_sha256 |
  | ceph-1 | "Ceph"  | "19.2.0"   | "85acea58"        |
  | pg-1   | "PGDG"  | -          | "0f3c11aa"        |
```

The corresponding JSON fragments are

```json
{
  "source": "notices",
  "fields": {
    "kind": "tool",
    "name": "Release notice inspection",
    "position": "L1"
  }
}
```

```json
{
  "fact": "Notice",
  "source": "notices",
  "columns": ["id", "holder"],
  "sourceColumns": ["revision", "fragment_sha256"],
  "rows": [
    [{"lit": "ceph-1"}, {"lit": "\"Ceph\""}, {"lit": "\"19.2.0\""}, {"lit": "\"85acea58\""}],
    [{"lit": "pg-1"}, {"lit": "\"PGDG\""}, {"boundary": "omitted"}, {"lit": "\"0f3c11aa\""}]
  ]
}
```

## Meaning

- A `source` declaration is a top-level declaration, also inside a `dataset`. Its indented lines are the fields of the source contract (`contracts/source.yaml`, class `Source`), one per line, in any order. `kind` takes a bare member of `SourceKind`; every other field takes a text literal. The JSON member `fields` holds them as strings, keyed by the contract name.
- `fact Kind @ name` adds the member `source` with the cited declaration's name. The declaration must be in the same module or dataset. A fact table without `@` has no source member and keeps the ordinary pack source of its module.
- A header cell `@ field` names a source field. Source columns follow the slot columns. The JSON keeps the slot names in `columns` and the field names in `sourceColumns`; each row holds the slot cells followed by the source cells. A source cell is a text literal, or a dash for "the declaration's value". A source column without a citation is refused.
- The source of a row is the declaration's fields, overridden by the row's source cells. It is validated exactly like a sidecar record whose `of` is the row's kind and identifier: the same required fields, patterns, document and third-party rules, and the same JSON-pointer shorthand for a `position` against the default's file.
- The published `sources.json` entry of each row is the one the equivalent `.sources.yaml` sidecar gives: a `default` for the declaration's fields and one `records` entry for every row with source cells.

## Considered

- **Keep the sidecar.** It works, but the fact and its source live in two files that must be edited together, and the module form would not carry the source span of either.
- **A separate `sources` table keyed by kind and id.** Closest to the sidecar, but it repeats every identifier, and its `kind` column would clash with the source field `kind`.
- **One `@ reference` per value, as in the v0 citation syntax.** Exact, but a fact table of thirty columns would carry thirty citations per row. A table-level citation with optional per-row fields covers every current sidecar.

Cell-level selectors (`of.slot`), several sources for one record and exact `rows` entries have no current use in any pack. They keep the sidecar until a pack needs them; a pack may use both forms, and a row with a source from both is refused.
