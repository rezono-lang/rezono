---
decider: [core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: feldera-calculation-parity
---

# Compare today's calculations on Feldera before a new derivation form goes there

The first-release proposal ([docs/rezono/first-release-proposal.md](../docs/rezono/first-release-proposal.md), Feldera rule 5) puts one view per functional derivation on Feldera, with value, state and reason in one row. The decision on that derivation form is pending. Its Feldera lowering builds on the current calculation views (`compiler/rezono_compiler/calc_sql.py`), and today nothing compares those views on Feldera in full. `compiler/tests/test_calc.py::test_feldera_gives_what_duckdb_gives` compares two programs written for the test, and `examples/test_feldera_rules.py::test_incremental_on_feldera_equals_batch` compares the rule views of the example packs and the known whole numbers that a rule reads from a calculation. No test compares a calculation's unknown or invalid rows, its reasons or its witnesses on Feldera, in a real pack.

## What must agree

For every example pack with `calc/` and fact states, at each fact state, Feldera, DuckDB and the checker agree:

- per calculation and subject, the state, the value, the reason, the definition and the version;
- the witnesses, as `calc_sql.witnesses` reads them from the witness relations;
- the checker (`rezono_checker.calc`) finds nothing in the witnesses read from Feldera, against the rows Feldera holds.

`examples/test_calculation_engine_parity.py::test_feldera_calculations_match_duckdb_and_checker` states this. Until it passes on hosted Feldera, the derivation form of the first-release language does not get a Feldera lowering.

## How it is compared

The test deploys only the pack's calculation pipeline (the part of `engine/pipelines.json` that holds `engine/calc.sql`). At each fact state it sends the same input rows that the DuckDB run reads: the facts, the parameters and the evaluation date, and the derived relations the calculation imports, as the DuckDB run of the rules gives them. `examples/test_feldera_rules.py` already compares those derived relations between Feldera and DuckDB, so the calculation is compared on equal input, in one pipeline instead of the whole chain.

It reads the rows of every rule view, version view and witness relation from Feldera, and puts them in a database with the DuckDB schema. The witness reader and the checker read that database as they read the DuckDB run, so neither gets a second implementation for Feldera.

## What this needs

- Every rule view, version view and witness relation is a `CREATE MATERIALIZED VIEW` in `engine/calc.sql`, so Feldera can be queried for it. Today the version views and witness relations are plain views. A materialized view holds its rows in the pipeline's storage; a witness relation has one column per cell of its version's expression.
- The live oracle runs the test: its selector in `compiler/ci/run_feldera_oracle.sh`, its case in the `subsidy` shard of `compiler/ci/feldera_shards.py`, outside `ORIGINAL`, as [the live Feldera oracle](live-feldera-ci.md) routes a new comparison. The `subsidy` shard already compiles that pack and downloads its dependencies, so no runner is added.

## Considered

- Extending `test_incremental_on_feldera_equals_batch`: it replays the whole chain of the pack, and a calculation difference there would be mixed with a rule difference upstream. A separate test keeps both reports apart.
- A Feldera reader of the witnesses beside `calc_sql.witnesses`: a second reader could disagree with the first, and the checker would then judge a different reading on each engine.
- Comparing only the exported calculation selections: that is what the rule comparison does now, and it leaves out exactly the rows a derivation form changes, unknown and invalid ones with their reasons.
