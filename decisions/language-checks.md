# Checks and conditional requirements

Retain warn and require for module checks. Inside a kind, 'require name when condition then consequence' stores an ordered checks entry with check, name, when and then members. Keep its description using schema metadata. Lower the two predicates to schema preconditions and postconditions where applicable. Preserve severity and rule descriptions: collapsing every failure to an unnamed Boolean loses published diagnostics.

```rezono
require active: shelf.open is known
```

The corresponding JSON fragment is

```json
{
  "check": "require",
  "name": "active",
  "cond": {
    "is": [
      {
        "path": [
          "shelf",
          "open"
        ]
      },
      "known"
    ]
  }
}
```
