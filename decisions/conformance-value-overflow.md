# Reason code for integer overflow

Source `docs/semantics/value-cases.yaml#overflow`.

## Deferral

Keep the overflow case deferred until the public reason vocabulary assigns a code for the sum above the signed integer bound. The [Value contract](../contracts/value.yaml) recognizes overflow as an invalid value and lists the undeclared core codes separately. That list does not assign `overflow`.

The migration needs a compiler and checker proof for the first out-of-range sum and a control at the bound. Compare both the invalid state and its published reason once that code has been assigned.
