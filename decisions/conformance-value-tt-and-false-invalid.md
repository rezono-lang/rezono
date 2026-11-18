# False decides conjunction with invalid

Source `docs/semantics/value-cases.yaml#tt-and-false-invalid`.

## Adopted behavior

A known false operand decides a conjunction even when the other operand is invalid. The result is a known Boolean false with no invalid reason carried into that result. The truth table is symmetric in the two operands.

Include both orders and a control where true is paired with invalid, which does carry the invalid state. The [normative truth tables](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and the [ordinary language evaluator](../rezono/test/evaluate.test.ts) cover every combination. Checks on the integrity of published inputs are evaluated separately.
