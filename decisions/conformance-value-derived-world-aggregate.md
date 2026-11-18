# Aggregating an open relation

Source `docs/semantics/value-cases.yaml#derived-world-aggregate`.

## Adopted behavior

A rule aggregating over an open relation needs a declared `absence` head. Without it the program is refused. With it the head is closed and the aggregate describes the rows recorded in the register. A separate scoped completeness premise is needed for a claim about the observed world.

Use the same aggregate with and without that declaration as the conformance pair. The [native rule decision](language-native-rules.md), [compiler world tests](../compiler/tests/test_rules_dl.py) and [independent checker world tests](../checker/tests/test_worlds.py) establish the distinction.
