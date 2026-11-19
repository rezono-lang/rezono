# Parameters and evaluation context

Keep typed parameters, per-kind scope and version syntax. Attach the importing pack's evaluation date by writing 'as of DAY known DAY' as a top-level declaration with asOf and known date strings. A row-backed parameter uses 'from Kind.value by name' and stores a source object with kind, slot and nameSlot strings. Do not substitute current values into the published definition: the valid and known axes select rows independently.

```rezono
param quota: Int per Shelf = 5
```

The corresponding JSON fragment is

```json
{
  "param": "quota",
  "type": "Int",
  "per": "Shelf",
  "value": {
    "lit": "5"
  }
}
```

## Explicit replacement

A version may say which version it replaces: `version 2 replaces 1`. This is precedence (a) of v0 section 5a, rule 4. It decides an overlap before the later `known` date does. The version member `replaces` holds the replaced version number as text.

```rezono
param quota: Int
  version 1, valid 2026-01-01.., known 2025-09-16 = 5
  version 2 replaces 1, valid 2026-01-01.., known 2025-09-16 = 6
```

The corresponding JSON fragment is the second version:

```json
{
  "version": "2",
  "replaces": "1",
  "valid": ["2026-01-01"],
  "known": "2025-09-16",
  "value": {"lit": "6"}
}
```

A replacement under a condition (`replaces 1 unless c`) is a later step. A number that names no version of the same declaration is R021.
