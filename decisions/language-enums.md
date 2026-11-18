# Ordered enumeration members

Retain the existing enum syntax, order and world. A deeper 'value low' block attaches metadata to that member under memberMetadata.low. Preserve descriptions and exact mappings using the schema metadata decision. Sorting members would change priority tables. The compiler carries the same order from a pack schema's `permissible_values` through the schema bundle into the published enumeration. An ordered lane over that enumeration uses the declared member order.

```rezono
enum Level world closed = low | high
```

The corresponding JSON fragment is

```json
{
  "enum": "Level",
  "world": "closed",
  "values": [
    "low",
    "high"
  ]
}
```
