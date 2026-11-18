# Conformance cases

[`sources.yaml`](sources.yaml) names the specification records to migrate. Each
`source` uses a repository-relative path and a record ID. A YAML fragment is the
value of the record's `id` field. In the publication pin decision, the fragment
identifies a row in the case table. The source retains the original wording and
status.

Write a case as `<id>.yaml` next to the inventory, using
[`case.schema.json`](case.schema.json). Use the neutral pack's input rows and the
settled behavior from the named specification. Record the expected value, value
state, reason and witness. Use `null` for an absent value, reason or witness.
When an engine cannot run a case, record its specific reason in `unsupported`
under `compiler`, `checker`, `feldera` or `language`.

For checker snapshot cases, put the accepted wire rows in `input.rows`.
Select a cell by its `key` and `slot` in `input.snapshot` and include a
`rejected` row for the counterexample. Record the checker's diagnostic
prefix in `expect.refusal`. The checker replays the JSON snapshot reader,
verifies that the accepted cells retain their wire fields, and checks
canonical premise spelling for an integer selected from an amount cell.

For an open or gap source, first record the adopted behavior and its rationale
in `decisions/conformance-<id>.md`. If a source will stay outside this corpus,
use the same decision path to record why it is deferred. Each decision cites
the exact `source` in backticks. Use `## Adopted behavior` when settling an open
case, or `## Deferral` when recording why there is no case.

The compiler test checks that the inventory matches the specification records
and validates the case files or their decisions. The migration check is an
expected failure until every source is accounted for. Engine tests establish
whether the declared expectations run and pass.
