# Admit round certificates at the batch boundary

A Loop round decides what may run from evidence that someone submitted. Treat a submitted safety verdict as a claim and give authority only to a certificate that admission checked against the protected round context. Use the same boundary and the same order as completeness receipts. [Scoped completeness](scoped-completeness.md) · [Safe transition rounds](safe-step-rounds.md) · [Admission of verified evidence](admission-transport.md)

## 1. Supplied verdicts block and never authorize

`loop_step_safety_check` rows and the `verdict` of `loop_batch_candidate` stay fact inputs. A supplied `refuted` or `unknown` verdict keeps its current meaning: it yields a `waiting` row with its obligation and reason. A supplied `proved` verdict authorizes nothing: `safe_alone`, `loop_certified_batch`, `loop_selected_batch` and `ready` follow only from the protected inputs of section 2. A supplied claim may still withhold a conclusion that would follow from its absence, such as a fixed point, because withholding is conservative.

The current meaning of `ready`, an eligible unfinished step with no waiting row, moves to `unblocked(run, step, reason)`. The fixed point, the Build task order and the typed recording read `unblocked`, so their behavior does not change when `ready` becomes certified membership.

A step without an admitted certificate is not ready. That alone adds no `waiting` row. `waiting` keeps identified obligations: an unmet need, a supplied blocking verdict, an ambiguous cut, or a finding of the certificate check. This keeps the reader's waiting reasons stable when no certificate was submitted, and keeps an unrelated step out of another step's result.

Options considered:

- Accept a supplied `proved` verdict as before. Rejected: a submitter who omits one obligation or one visible boundary could authorize an unsafe step (`test_ready_requires_checked_batch_member`, `test_overlapping_withdrawals_break_availability`).
- Ignore supplied verdicts entirely. Rejected: a refutation is conservative and only blocks, so it is safe to keep as a fact, and existing waiting reasons depend on it.

## 2. Protected round inputs

`std-loop` reads the protected relations that [admission of verified evidence](admission-transport.md) reserves in its section 6, and declares them with exactly those signatures and no clause:

```prolog
.decl verified_round(round: symbol, run: symbol, cut: symbol, batch: symbol)
.decl verified_round_member(round: symbol, step: symbol)
```

No fact, rule, proposal or scenario row may supply them. Only admission of a round claim fills them, with the claim digest as `round` so a witness can cite it. As section 8 of that decision fixes:

- `safe_alone(run, step, cut)` follows from a verified round of the current run and cut whose batch has exactly that one member.
- `loop_certified_batch` and `loop_selected_batch` follow from a verified round of the current run and cut, with the round's batch as the batch. The round verifier has already replayed the choice, so the admitted batch is both certified and selected.
- `ready` holds the members of that round that have no waiting row.

A round for an earlier cut authorizes nothing at the current cut.

The speculative selection in `loop/batch_selection.py` is part of the certifier, not a publication. Inside its own evaluation it may keep the verdict-based selection under internal names. Those relations are not admission inputs.

The names `loop_certified_step` and `loop_certified_member` of an earlier draft lapse.

## 3. Transport

The protected caller hands one `Evidence` to `batch.epoch`, as [admission of verified evidence](admission-transport.md) fixes in sections 2 to 4:

| Part | Holds |
| --- | --- |
| `context` | The archived-file reference to `observations/retained/context.json`: `completeness` lists the trusted receipt contexts and `rounds` the trusted round contexts. A round context pins `run`, `cut`, `manifest`, `definition_sha256`, the compiled `program`, the `invariants`, the `observations`, the certified `base` and the `domain` with its steps, integer priorities and batch width. |
| `candidates` | The archived-file reference to `observations/submitted/index.json`: `completeness_receipts` and `rounds` list the submitted receipts and round claims. A round claim names `run`, `cut`, `batch`, `members` and, per visible subset, its `members`, `variant` and `certificate`. Candidates select bytes to check and confer no authority. |
| `read_bytes` | The storage resolver of the snapshots. |

Admit receipts first, then rounds, because a certificate cites receipts for its scoped negations. The round verifier in the checker builds its context only from the retained round context and replays the batch choice. A rejected candidate yields no row and a warning, and the publication stays green. The checker repeats admission when it checks the epoch. The publisher lists the candidate references in the complete manifest under `completeness_receipts` and `rounds`, and never publishes the trusted context.

The keywords `completeness_receipts`, `completeness_authority`, `transition_certificates`, `transition_authority` and `archive` of an earlier draft lapse. The Loop test helpers change in one place: `loop/tests/round_visibility_publication.py`, which `published_selection` in `loop/tests/test_mapped_path_requires_reader_inventory.py` reuses.

## 4. Test fixtures

In Loop and Build tests, retained objects form the trusted context and submitted objects are candidates. Both are stored in one archive. The helpers write `context.json` and `index.json` and hand both to the batch boundary as one `Evidence`. A test never derives trust from the archive by listing it.

A Loop round domain lists each step with its integer priority and its effect plans in order. A step with more than one ordered effect has visible boundaries between them, and a subset of such a step in a round claim names the effects applied at that boundary. A Build completeness context has exactly the six receipt fields; the repository bundle from which the protected job derived them stays retained beside it.
