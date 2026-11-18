# Evaluating an unresolved version overlap

Source `docs/semantics/value-cases.yaml#version-overlap`.

## Deferral

[Rezono v0 §5a](../docs/rezono/v0.md#5a-validity-and-applicability-contexts) requires `invalid versions_overlap` and both witnesses when two applicable versions share a knowledge date and no explicit replacement settles precedence. The [publication lowering](../docs/rezono/publication.md#4-value-states) specifies this meaning and records that versioned definitions themselves are outside the supported slice.

Revisit with an actual version-selection path that emits both witnesses and a control where a later knowledge date or explicit replacement resolves the overlap. A fixture that supplies an already-invalid scalar cannot establish how the selector chose its result.
