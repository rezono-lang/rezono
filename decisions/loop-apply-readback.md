---
decider: [loop]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: loop-apply-readback
---

# One executor applies and reads back

[Run-scoped reconciliation](loop-design.md) names one executor for planning, applying, observing and replaying. The deciding half exists: `loop/typed_recording.py` evaluates the pinned std-loop pack on each recorded sweep, `loop/replay.py` turns the snapshots into frontiers and an outcome, and `loop/recording_cli.py` replays a recording without a cluster. The field read-back exists separately in `loop/readback_roundtrip.py`. Nothing yet applies a planned step and reads back what it changed. Building a platform from an empty cluster needs exactly that path, so it comes before the remaining loop work: moving `loop/round_outcome.py`, `loop/flow_evidence.py`, `loop/status_projection.py` and `loop/status_visibility.py` into rules, and the live disposable-cluster runs.

## Interface

`loop/executor.py` provides `execute(directory, data, *, apply, read) -> tuple[dict, dict]`.

- `data` is a typed recording whose `sweeps` are empty or absent: `run`, `limit`, `initial`, `ports`, `pack`, `records` and an optional `clock`, with the meaning [Run-scoped reconciliation](loop-design.md) gives them under "Recorded corrections". `directory` resolves the relative pack path. The ports name exactly one port of kind `effect` and at least one reader of kind `in` that produces `loop_observation`; anything else is a `ValueError` before the first round.
- `apply(run, round, step)` performs one planned step through the effect port. Rounds count from 1.
- `read(run, round)` returns one dated sweep: `id`, `run`, `event_time`, `complete` and `observations`, each observation a run-scoped Observation envelope from a declared reader. It is called exactly once per round, after every apply of that round, even when the round planned nothing.

## Rounds

Each round evaluates the pinned pack on the evidence so far through the same code that replay uses; the executor has no second evaluator. If the outcome is no longer pending, the run stops. Otherwise the executor applies the ready frontier in step-key order, reads one sweep, appends it to the recording and evaluates again. The round bound and the fixed-point failure are those of replay.

## What counts as done

The value `apply` returns is never evidence. A step is done only when the pack derives `done` from read-back evidence of the active run whose value equals the expectation. A step whose apply returned while the read-back stays silent remains ready and is planned again, up to the bound; its successors are never applied.

A read-back value that differs from the expectation is a `drift` row of the pack, not a completion. It makes the outcome `failure` and is reported as a finding with both references: `{"token", "desired", "observed"}` from the drift row, where `observed` is the envelope reason. No later step is applied after it.

## Report and recording

The report has the keys of the recording command (`plans`, `outcome`, `rounds`, and `fixed_point` when present) plus `findings`, a sorted list that is empty when nothing drifted. The returned recording is `data` with `sweeps` set to the sweeps `read` returned, in order. It is plain JSON. Replaying it with `python -m loop.recording_cli` gives the same `plans`, `outcome` and `rounds` without a cluster. That replay is the offline proof of every executed run.

## Order of work

1. `test_executor_applies_then_reads_back`: the module, the rounds and the report.
2. `test_apply_result_is_not_evidence`: a silent read-back keeps the step open.
3. `test_readback_mismatch_is_a_finding`: drift stops the run with evidence.
4. `test_executed_run_replays_offline`: the recording replays to the same plans and rounds.

Each later test may wait for the earlier ones. After these four, the existing quiet-round, certified-replay and live startup tests use this executor as their shared entry point.

## Alternatives

A separate live loop beside replay would let the live and recorded decisions diverge, so the executor reuses the replay evaluation. Trusting the apply result would count a step as done before the world shows it, which is exactly what read-back is for. Reporting a mismatch as a plain failure without its rows would hide the evidence the reader needs.
