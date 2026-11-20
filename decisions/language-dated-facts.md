# Dated facts

A fact about one record can hold for a period, and become known on a day. It is written as a fact row with a context after the record: `fact party p1, valid 2026-01-01..<2027-01-01, known 2025-12-01`, followed by its assignments, one per line. This is the version syntax of the [language reference](../docs/rezono/v0.md), section 5a, for facts. The fact row keeps `fact` with the snake-case kind and `id` with the record, then `valid` as one or two dates (the first day, and the day after the last one; one date for a range without an end), `known` as a date, and `set` with the assignments (contracts/rezono-module.yaml, `FactRow`).

```rezono
fact party p1, valid 2026-01-01..<2027-01-01, known 2025-12-01
  size = 3
fact party p1, valid 2027-01-01.., known 2026-12-01
  size = 4
```

The corresponding JSON fragment is the first row:

```json
{
  "fact": "party",
  "id": "p1",
  "valid": ["2026-01-01", "2027-01-01"],
  "known": "2025-12-01",
  "set": [
    {"slot": "size", "value": {"lit": "3"}}
  ]
}
```

## Meaning

- **Each row is a version of the values it sets,** for the record it names. Values it does not set keep their other versions.
- **Selection follows v0 section 5a.** For an evaluation date and a knowledge date, the versions whose period holds the date and whose `known` date is on or before the knowledge date apply. Among them the one with the later `known` date wins on the overlap. No version gives `unknown no_version_applies`; two with the same `known` date on an overlap give `invalid versions_overlap`.
- **Order and identity.** Rows keep their source order. The same record may appear in several rows. A dated row never creates the record: an undated row or a fact table does.

Lowering needs a place for versioned values in the fact contracts. That place, and the admission of these rows, belong to the fact and contracts work after the base fact table lowers.

## Considered

- **One row per record with a list of versions.** It would move the dates away from the values they qualify and differ from how parameters and derived values write versions.
- **Separate valid-from and valid-until slots on the kind.** Every versioned slot would need its own pair, and a correction known later could not be told apart from a change of period.

## Stage and setup contexts

A fact row may also hold for a range of stages or for some setups, the other two axes of v0 section 5a. They stand after the record, before `known`, in the order of that section's table: `valid`, `during`, `in`, `known`.

| Rezono | Member |
|---|---|
| `during stage-a` | `"during": {"stage": "stage-a"}` |
| `during stage-a..<stage-c` | `"during": {"from": "stage-a", "until": "stage-c"}` |
| `during stage-c..` | `"during": {"from": "stage-c"}` |
| `in setup-a \| setup-b` | `"in": ["setup-a", "setup-b"]`, in the order written |

```rezono
fact party p1, during stage-a..<stage-c, known 2026-01-05
  size = 3
fact party p3, valid 2026-01-01.., in setup-a | setup-b
  size = 6
```

A stage context is an object, not a list like `valid`: one stage and an open range starting at that stage are different contexts, and a list of one would not tell them apart. The stage and setup names are record identifiers, written as a fact row writes its record. The module form contract gains the two members on `FactRow`.

## Lowering

`facts.load(pack, path, *, as_of: str | None = None, known: str | None = None)` in `compiler/rezono_compiler/facts.py` lowers dated `FactRow` declarations inside a named dataset (`rezono.module/2`) alongside its base fact tables:

- **Existing records only.** Every dated row must reference a record identifier created by a fact table or undated row in the same dataset. A dated row for an unknown record is refused with `LoadError`.
- **Typed slot admission.** Each assignment in `set` names a declared slot of the kind and its value is decoded and checked under the same schema admission rules as fact tables.
- **Version selection on `(as_of, known)`.** When `as_of` and `known` are ISO dates (`YYYY-MM-DD`), a dated row applies to `(record, slot)` when `valid[0] <= as_of`, `as_of < valid[1]` if an end date is given, and `row.known <= known` if the row specifies `known`.
  - If no dated row applies to `(record, slot)`, no row is emitted in `kind__slot` for that record (unknown / `no_version_applies`).
  - If one applying row has a strictly later `known` date than all other applying rows (with an explicit `known` date preferred over an omitted one), its typed value is emitted as `(record, value)` in `kind__slot`.
  - If two or more applying rows tie on the latest `known` date on an overlap, `facts.load` refuses the dataset with `LoadError` naming `versions_overlap`.

The lowering test is `compiler/tests/rezono/test_lower_dated_fact.py`.
