# Kinds and identity

Keep the existing kind block. An explicit identifier replaces the implicit id. An anonymous kind uses 'embedded kind' and has no identifier. An abstract kind uses 'abstract kind'. A subtype writes 'kind Member is Person'. The respective optional kind members are embedded and abstract (true when written) and parent (a kind name). Inherited identifiers resolve through the parent. Reject competing identifiers. Always synthesizing id would change both embedded records and existing keys.

```rezono
kind Branch
  code: Text identifier
```

The corresponding JSON fragment is

```json
{
  "kind": "Branch",
  "slots": [
    {
      "slot": "code",
      "type": "Text",
      "identifier": true
    }
  ],
  "derived": []
}
```
