# An invalid condition makes an answer undecided

Source `docs/semantics/value-cases.yaml#value-invalid-blocks`.

## Adopted behavior

An invalid value used by an `ask` produces an `Undecided` row for that binder. The row preserves the invalid state, reason and cause. An answer classification alone does not block publication. Check and require statements apply their own publication rules.

The same input can therefore make a query undecided and block a check. Preserve that distinction in the case. [Rezono v0 decision points](../docs/rezono/v0.md#7b-truth-and-value-states) and the [language evaluator tests](../rezono/test/evaluate.test.ts) show both paths.
