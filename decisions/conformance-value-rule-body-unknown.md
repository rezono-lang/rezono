# Unknown premises in a rule outcome

Source `docs/semantics/value-cases.yaml#rule-body-unknown`.

## Deferral

The [language's decision table](../docs/rezono/v0.md#7b-truth-and-value-states) assigns an outcome state to an undecided rule condition. The [publication lowering](../docs/rezono/publication.md#4-value-states) uses set-valued rules for conclusion rows and named outcomes for state and reason. The source writes an ordinary `fits` rule and expects a state for every host and plan binding.

Revisit once a public native rule example specifies which output records carry these outcomes, their binding key, and the witness of the missing fact. A case that records only the absence of a conclusion would omit the source's stated outcome.
