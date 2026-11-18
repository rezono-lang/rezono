# Minimum of a known empty set

Source `docs/semantics/value-cases.yaml#agg-min-empty`.

## Adopted behavior

The scalar minimum of a known empty set has state `not_applicable` and reason `empty`. It has no result payload or contributing member. The absence of members is the relevant evidence.

The case should distinguish this result from the minimum of a one-member set, which is known and has a contributor. Use the [Rezono aggregate semantics](../docs/rezono/v0.md#7b-truth-and-value-states) and the [language evaluator's empty-set tests](../rezono/test/evaluate.test.ts).
