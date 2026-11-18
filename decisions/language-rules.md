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

## Clause evidence and source locations

A proof for a relational block retains the rule identifier, head, ordered premises, polarity, stratum and typed variable bindings of the authored relational rule. For presentation, resolve that identifier to the rule message and the output relation label in the published language. Verify that both the premise key and conclusion key resolve in their respective snapshots.

The authored pair in `compiler/tests/rezono/fixtures/listed/` states one rule. An Alpha fact with key a implies listed(a); its only witness binds x to a and uses the positive Alpha row at stratum zero. The ordinary rule file and the Rezono block must publish this meaning. The rule origin and span point to the head of the clause in each file. The two spaces, vertical bar and separator in the block precede the source column. Report the authored location even when lowering constructs temporary rule text.

The compiler test consumes a hand-authored module/2 form so its implementation can proceed independently of the reader after the module contract admits relational blocks. The separate reader case checks preservation of declaration, clause and output lines in order.
