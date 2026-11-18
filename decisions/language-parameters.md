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
