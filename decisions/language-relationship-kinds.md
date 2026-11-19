# Relationship kinds

A kind whose records are links between other records writes `relationship kind`, in the same place as `abstract kind` and `embedded kind`. The kind member `relationship` is `true` when written and absent otherwise. It lowers to LinkML `represents_relationship: true`, so the compiler derives the kind's ends and its two-end key check exactly as for a schema file. A subtype inherits the marker through its parent.

```rezono
relationship kind Ground world closed
  decision: Decision
  rests_on: Decision
```

The corresponding JSON fragment is

```json
{
  "kind": "Ground",
  "world": "closed",
  "relationship": true,
  "slots": [
    {"slot": "decision", "type": "Decision"},
    {"slot": "rests_on", "type": "Decision"}
  ],
  "derived": []
}
```

`relationship` combines with `abstract` (`abstract relationship kind`) and with a parent (`relationship kind Ground is Link`), in that order. It does not combine with `embedded`: an embedded record has no identity of its own and cannot be an end-named link. The reader refuses that combination.

## Considered

- **An annotation line, `annotation represents_relationship = true`.** It would lower without new grammar, but the marker changes keys and checks; it is part of the kind's meaning, not metadata.
- **Infer a relationship from two required kind-valued slots.** Many ordinary kinds have two such slots. Inference would silently change their keys.
- **An explicit `false` on a subtype.** LinkML allows a subtype to switch the inherited marker off. No pack does so; the spelling waits until one needs it.
