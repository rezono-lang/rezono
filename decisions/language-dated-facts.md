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
