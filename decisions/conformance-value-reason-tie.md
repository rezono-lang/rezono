# Choose the least reason in the highest state

Source `docs/semantics/value-cases.yaml#reason-tie`.

## Adopted behavior

An arithmetic result with two unknown operands carrying `zz_late` and `aa_early` is unknown with reason `aa_early`. Order the reason codes by UTF-8 within the winning state. The cause belongs to the winning reason, and equal reasons use their cause's ordering.

Reverse the operands to check that the reason is invariant. Add a higher-state operand to verify that state is selected before reason. The [language reason rule](../docs/rezono/v0.md#7b-truth-and-value-states) and the [evaluator's reason controls](../rezono/test/evaluate.test.ts) distinguish this rule from selection by operand position.
