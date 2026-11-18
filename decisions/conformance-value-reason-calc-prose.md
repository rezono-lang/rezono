# Code for a missing calculation fact

Source `docs/semantics/value-cases.yaml#reason-calc-prose`.

## Deferral

The [Value contract](../contracts/value.yaml) gives state reasons a code and the [publication lowering](../docs/rezono/publication.md#4-value-states) assigns `no_value` to a missing slot in a named outcome. This source examines a calculation proof leaf. The [tracked calculation fixture](../checker/tests/fixtures/calc/witnesses.json) still represents that leaf's reason as prose.

Revisit when the calculation witness producer and independent checker agree on the leaf's reason code, its fact reference and the separate catalogue text. Assigning the outcome's code to the leaf without that mapping could lose the evidence of which fact was missing.
