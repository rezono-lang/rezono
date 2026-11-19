# Admit round certificates at the batch boundary

A Loop round decides what may run from evidence that someone submitted. Treat a submitted safety verdict as a claim and give authority only to a certificate that admission checked against the protected round context. Use the same boundary and the same order as completeness receipts. [Scoped completeness](scoped-completeness.md) · [Safe transition rounds](safe-step-rounds.md)

## 1. Supplied verdicts block and never authorize

`loop_step_safety_check` rows and the `verdict` of `loop_batch_candidate` stay fact inputs. A supplied `refuted` or `unknown` verdict keeps its current meaning: it yields a `waiting` row with its obligation and reason. A supplied `proved` verdict derives nothing. `safe_alone`, `loop_certified_batch`, `loop_selected_batch` and `ready` follow only from the protected inputs of section 2.

The current meaning of `ready`, an eligible unfinished step with no waiting row, moves to `unblocked(run, step, reason)`. The fixed point, the Build task order and the typed recording read `unblocked`, so their behavior does not change when `ready` becomes certified membership.

A step without an admitted certificate is not ready. That alone adds no `waiting` row. `waiting` keeps identified obligations: an unmet need, a supplied blocking verdict, an ambiguous cut, or a finding of the certificate check. This keeps the reader's waiting reasons stable when no certificate was submitted, and keeps an unrelated step out of another step's result.

Options considered:

- Accept a supplied `proved` verdict as before. Rejected: a submitter who omits one obligation or one visible boundary could authorize an unsafe step (`test_ready_requires_checked_batch_member`, `test_overlapping_withdrawals_break_availability`).
- Ignore supplied verdicts entirely. Rejected: a refutation is conservative and only blocks, so it is safe to keep as a fact, and existing waiting reasons depend on it.

## 2. Protected round inputs

Reserve two base relations in the same way as `verified_receipt`:

```prolog
.decl loop_certified_step(run: symbol, cut: symbol, step: symbol, certificate: symbol)
.decl loop_certified_member(run: symbol, cut: symbol, batch: symbol, step: symbol, certificate: symbol)
```

No fact, rule, proposal or scenario row may supply them. Only admission of a transition certificate fills them, with the certificate digest as the last column so a witness can cite it. `std-loop` derives `safe_alone` from `loop_certified_step` and the certified and selected batch from `loop_certified_member`.

The speculative selection in `loop/batch_selection.py` is part of the certifier, not a publication. It evaluates the same rules and supplies these inputs to its own evaluation from the verdicts it was given.

## 3. Transport

The protected caller passes the round candidates and the trusted round context to `batch.epoch` next to the receipt transport, resolved through the same `archive`:

| Keyword | Holds |
| --- | --- |
| `completeness_receipts`, `completeness_authority` | As decided in scoped completeness, section 1. |
| `transition_certificates` | Archived-file references to every submitted round object: certificates and the batch choice. They select bytes to check and confer no authority. |
| `transition_authority` | One trusted context per round: run, cut, and archived-file references to every retained object of that round, such as the compiled definition, the observed inputs and their inventory, the desired manifest and the effect declarations. |

Admit receipts first, then certificates, because a certificate cites receipts for its scoped negations. The round verifier in the checker rebuilds the obligation inventory and the visible boundaries from the trusted context and replays the batch choice. A rejected candidate yields no row and a warning, and the publication stays green. The checker repeats admission when it checks the epoch. The publisher lists the candidate references in the complete manifest and never publishes the trusted context.

If core chooses other keyword names, the Loop test helpers change in one place: `loop/tests/round_visibility_publication.py` and `published_selection` in `loop/tests/test_mapped_path_requires_reader_inventory.py`.

## 4. Test fixtures

In Loop and Build tests, retained objects form the trusted context and submitted objects are candidates. Both are stored in one archive. The helpers hand both to the batch boundary. A test never derives trust from the archive by listing it.
