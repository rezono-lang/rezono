# Classifying true, unknown and inapplicable answer bindings

Source `docs/semantics/value-cases.yaml#ask-undecided`.

## Adopted behavior

A true filter appears in `Answer`. An unknown filter appears in `Undecided` with the binder, the reason `not_assigned` and the RowRef of the owner slot. An inapplicable filter increases the inapplicable count. A false filter contributes to none of those categories.

Use the state and cause observed by the normal evaluator to construct the neutral case. The [language decision rules](../docs/rezono/v0.md#7b-truth-and-value-states), [E42](../docs/rezono/cases/E42.yaml) and the [answer tests](../rezono/test/evaluate.test.ts) agree on those observations.
