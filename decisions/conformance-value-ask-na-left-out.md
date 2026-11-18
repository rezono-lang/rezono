# Negation preserves an inapplicable answer condition

Source `docs/semantics/value-cases.yaml#ask-na-left-out`.

## Adopted behavior

Negating an inapplicable comparison yields an inapplicable condition. The binder contributes to the inapplicable count for either polarity. An unknown comparison remains undecided with its reason in both questions.

Use the positive comparison and its written negation against the same inputs. The [decision rules](../docs/rezono/v0.md#7b-truth-and-value-states), [E43](../docs/rezono/cases/E43.yaml) and the [evaluator](../rezono/test/evaluate.test.ts) give this control.
