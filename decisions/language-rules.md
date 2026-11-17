# Relational rules

Use an indented block of lines prefixed with a vertical bar and one separator space. Preserve the remainder of each line, including rule annotations, blank lines, output declarations and comments. Join with LF and a final LF, and validate using the existing rules parser. This admits recursion, joins, negation and aggregations without introducing competing evaluation semantics. A calculation expression alone cannot express every relational rule.

```rezono
rules inventory
  | .decl ready(x: symbol)
  | ready(x) :- shelf(x).
  | .output ready
```

The corresponding JSON fragment is

```json
{
  "rules": "inventory",
  "lines": [
    ".decl ready(x: symbol)",
    "ready(x) :- shelf(x).",
    ".output ready"
  ]
}
```
