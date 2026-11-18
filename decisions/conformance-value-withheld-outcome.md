# Withholding a named outcome

Source `docs/semantics/value-cases.yaml#withheld-outcome`.

## Deferral

The [manifest contract](../contracts/manifest.yaml) requires complete readable proof premises for a role and full access for aggregates and negation. The source does not say whether its outcome depends on a positive proof, an aggregate, or negation. Those proof shapes give different grounds for withholding a row.

Revisit with an explicit named outcome rule, a role that reads the required relation in part, and a role with full read evidence. The case also needs a two-world check before assigning any publicly visible state or reason to the withheld outcome.
