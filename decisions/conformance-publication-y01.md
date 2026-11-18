# The published answer schema

Source `docs/publication/cases/Y01.yaml#Y01`.

## Deferral

The [language evaluator](../rezono/test/evaluate.test.ts) tests a typed answer with `Answer` and `Undecided`. This source concerns the published response for the two-column question in [E51](../docs/rezono/cases/E51.yaml), including its output-schema ID. The ordinary publication request path is unavailable in this corpus.

Revisit when a real answer request returns a schema ID and both record kinds. Verify the two projected columns and the cause fields from the response rather than copying the evaluator's local schema into a fixture.
