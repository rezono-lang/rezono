# Home claim for the subsidy example

The subsidy home states the day on which the scheme is evaluated. The scheme facts supply exactly one evaluation day. Every published scenario concerns an application, household, payment or decision and retains that day.

Use the derived relation `scheme_evaluation_day` with the day identifier as its sole column. Its single rule projects the identifier of the evaluation day. The pack provides a reader-facing sentence for that rule in every supported language. Select the relation in the example channels and preserve the current hero when present.

A per-application award would produce several rows. A payment or finding can disappear in a scenario. The evaluation day applies to the entire scheme and remains meaningful across these states. The generic example test independently verifies the cardinality of the published snapshots.
