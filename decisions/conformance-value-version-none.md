# Evaluating a version gap

Source `docs/semantics/value-cases.yaml#version-none`.

## Deferral

[Rezono v0 §5a](../docs/rezono/v0.md#5a-validity-and-applicability-contexts) specifies `unknown no_version_applies` when no version holds. The [reader test](../rezono/test/module.test.ts) demonstrates W108 for an initial gap. The [publication lowering](../docs/rezono/publication.md#4-value-states) records that this slice refuses versioned declarations.

Revisit with an ordinary runtime case that evaluates the day before validity, publishes the unknown state and reason, and evaluates the first valid day as a control. W108 verifies a source warning and leaves that runtime result untested.
