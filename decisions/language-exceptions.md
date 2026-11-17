# Ordered exceptions

Keep the existing unless form under a derived value, including ordered groups and source citations. Preserve the separation between an unconditional fallback and an unknown condition. Reordering exceptions could change a publication.

```rezono
unless paused then 0
```

The corresponding JSON fragment is

```json
{
  "unless": [
    [
      {
        "when": {
          "path": [
            "paused"
          ]
        },
        "then": {
          "lit": "0"
        }
      }
    ]
  ]
}
```
