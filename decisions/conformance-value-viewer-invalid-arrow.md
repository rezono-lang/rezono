---
decider: [core, language]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: superseded
subject: viewer-invalid-sign
---

# Displaying an invalid reference

Source `docs/semantics/value-cases.yaml#viewer-invalid-arrow`.

## Deferral

Superseded by [`decisions/std-view-invalid-sign.md`](std-view-invalid-sign.md): `invalid` uses the dedicated `!` status sign and `status.invalid` palette token in `packs/std-view` and the slip model (`viewer/slip/src/model.ts`), distinct from both `violated` (`✕`) and `unknown` (`▨`). The separate map/flow drawing conformance case remains deferred until drawing views are covered in the conformance corpus.
