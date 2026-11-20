---
decider: [language]
decided_on: 2026-11-19
valid_from: 2026-11-19
state: in_force
subject: standard-pack-candidates
---

# Staging candidates for ready standard packs and examples

The usage inventory marks five remaining standard packs (`packs/std-decision`, `packs/std-identity`, `packs/std-order`, `packs/std-part`, `packs/std-time`) and the standalone example `examples/projects` Ready for first conversion into `.rezono` modules. Converting all six in parallel without disturbing existing pack hashes or legacy oracle tests follows the staging pattern already used for `examples/library` ([Acceptance of the library migration](language-library-acceptance.md)).

## Decision

1. **Stage each candidate in `<pack>/candidate/`.** For a standard pack `packs/std-<name>`, the candidate holds `<name>.rezono` and `<name>.json` (generated from the `.rezono` source by `rezono/src/write-form.ts`). For `examples/projects`, the candidate holds `projects.rezono`, `valid.rezono`, `errors.rezono` and their `.json` forms, matching the three-module layout of `examples/library/candidate/`.
2. **Keep the existing pack intact as the live oracle.** `candidate/` is not in `DEFINITION` of `compiler/rezono_compiler/modules.py`, so staging a candidate leaves `pack_hash`, every importing `pack.yaml`, `examples/test_examples.py`, and the Soufflé oracle tests untouched. Each conversion task is therefore independent of every other pack conversion.
3. **Compare isolated builds in the whole-pack test.** Each pack has its own whole-pack test under `compiler/tests/rezono/test_whole_<name>.py`. The test builds two isolated copies in a temporary directory:
   - **Legacy:** the existing pack as checked in (`schema/` and `rules/` or `facts/`).
   - **Candidate:** the pack with `schema/` and `rules/` (or `facts/`) omitted, `candidate/` copied to `rezono/`, and `pack.yaml` declaring the candidate module entries.
   Both isolated packs must agree on:
   - the semantic schema bundle (kinds, enums, arrows, attributes, annotations, mappings, checks, unique keys, path equations, labels, messages, channels, with source file and spans normalised to the pack),
   - the compiled rule IR, derived relations and invariants (or, for `examples/projects`, the loaded rows and violation findings for both `valid` and `errors` datasets, also checked against `examples/projects/expected/violations/`), and
   - exact batch evaluation over representative scenarios and counter-cases (plus compilation through an importing consumer copy where applicable).
   The test also verifies that the language reader reproduces each candidate `.json` form byte-for-byte from its `.rezono` source.
4. **Cutover after Soufflé and example harnesses accept modules.** Once a candidate test is green and the Soufflé test helpers (`compiler/tests/souffle.py` and the theory tests) read rule blocks from `rezono/` modules as well as `rules/*.dl`, a follow-up cutover moves `candidate/` to `rezono/`, removes the legacy `schema/` and `rules/` (or `facts/`) files, updates import pins where required, and records the verified semantic expectations.

## Considered

- **Replacing `schema/` and `rules/` immediately in every standard pack.** Five parallel tasks would collide on importing `pack.yaml` files (`examples/platform/pack.yaml`, `examples/subsidy/pack.yaml`, `run/packs/*/pack.yaml`) and would break the Soufflé oracle tests (`compiler/tests/souffle.py`, `test_std_decision.py`, `test_theory_*.py`), which currently glob `rules/*.dl` directly.
- **Waiting to convert any more standard packs until Soufflé helpers are updated.** Staging candidates lets all six packs be authored, reviewed and proven semantically equivalent in parallel right now without waiting on another track.
