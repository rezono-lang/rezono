# Unknown outranks inapplicable in an undecided conjunction

Source `docs/semantics/value-cases.yaml#ask-unknown-outranks-na`.

## Adopted behavior

A conjunction of inapplicable and unknown is unknown when neither operand is false. The answer includes an undecided binder with the reason of the unknown operand. For the recorded example that reason is `no_spec`. That binder does not increase the inapplicable count.

Compare with the same binder after the unknown input is replaced by a known value that makes the comparison true. The conjunction is then inapplicable. The [normative truth tables](../docs/rezono/expressions.md#appendix-a-truth-tables-normative) and [E45](../docs/rezono/cases/E45.yaml) define the expected result.
