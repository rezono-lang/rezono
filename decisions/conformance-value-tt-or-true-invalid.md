# True decides disjunction with invalid

Source `docs/semantics/value-cases.yaml#tt-or-true-invalid`.

## Adopted behavior

A known true operand decides a disjunction even when the other operand is invalid. The result is a known Boolean true with no invalid reason carried into that result. Swapping the operands preserves it.

Include both orders and a control where false is paired with invalid. That control carries the invalid state. The [normative truth tables](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and the [ordinary language evaluator](../rezono/test/evaluate.test.ts) exercise these cells.
