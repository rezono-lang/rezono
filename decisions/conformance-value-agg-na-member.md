# A sum preserves an inapplicable member

Source `docs/semantics/value-cases.yaml#agg-na-member`.

## Adopted behavior

For an otherwise known set containing the quantities 3 and 4 and one inapplicable member with reason `not_assigned`, the scalar sum has state `not_applicable` with that reason. An observed inapplicable member takes part in state propagation.

Include a control where every member is known and the sum is 7. The [strict aggregate and reason rules](../docs/rezono/v0.md#7b-truth-and-value-states) and the [language evaluator's aggregate tests](../rezono/test/evaluate.test.ts) distinguish those inputs.
