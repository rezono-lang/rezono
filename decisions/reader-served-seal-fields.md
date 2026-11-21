---
decider: [core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: reader-served-seal-fields
---

# Reader-served seal fields: trust tier, `may_propose`, reader hash check, and origin signs

Tracking issue: [rezono-lang/rezono#1451](https://github.com/rezono-lang/rezono/issues/1451).
Companion viewer plan: `rezono-lang/cartouche` Decision 0015 (`m1-propose-locked-until-served`, `m1-reads-only-served-head-fields`, `m2-seal-and-rights-from-rezono`).

## Context

[The slip decision](viewer-slip.md) fixes that the browser viewer computes nothing and has no answer of its own to any question.
Until now, the local reader (`edge/gate/src/local.ts`) served only `witness_check` and `manifest_sha256` on `GET /<pack>/head`, omitted a served hash-verification result on `GET /<pack>/<manifest>/ask/grounds`, and carried only `kind` (for example `"synthetic"`) on fact sources.
Viewers therefore had no served field to quote for:
1. the trust tier of what `/<pack>/head` serves;
2. whether the reader's role holds a `may_propose` grant on this publication;
3. the reader's own hash check result per witness on `/<pack>/<manifest>/ask/grounds`;
4. the epistemic origin sign of each fact source (`origin_decision`, `origin_vendor`, `origin_design`, `origin_observation` from `packs/std-view/key.yaml`).

## Decision

### 1. `trust_tier` on `GET /<pack>/head`

`GET /<pack>/head` serves `trust_tier` (enum `TrustTier` in [contracts/explain.yaml](../contracts/explain.yaml)) for the role's current head:
- `sealed`: a published main manifest served from the store whose `witness_check` is `"green"` (all published checks and witnesses verified and every store object hashed by the reader).
- `provisional_checked`: a published manifest whose `witness_check` is absent or not `"green"`, or a published counterfactual/sweep variant or proposal manifest.
- `provisional_engine`: a live unsealed engine stream (never emitted by the static local reader over a published store; reserved for live unsealed engine endpoints).

Viewers quote `trust_tier` verbatim and never compute it from `witness_check` or manifest ids.

### 2. `may_propose` on `GET /<pack>/head`

The publisher projects each role's own derived `may_propose(role, kind, element)` rows (`packs/std-access/rezono/access.rezono`) into that role's published slice, strictly filtered to rows whose `role` matches the target role so other roles' proposal grants never leak across roles.
The checker verifies the derived `may_propose` relation as an ordinary rule derivation.
`GET /<pack>/head` then reads only that published role-scoped truth (never computing rights in the gate) and serves `may_propose` (boolean):
- `true` if and only if the authenticated role's published `may_propose` projection for the current manifest contains at least one row for this role.
- `false` otherwise (including when the pack defines no `may_propose` grants for the role).

Viewers never infer proposal rights from `witness_check`, `trust_tier`, or local role names.
When `may_propose` is `false` (or absent on older readers), proposal actions stay locked.

### 3. `reader_hashes` on `GET /<pack>/<manifest>/ask/grounds`

[contracts/explain.yaml](../contracts/explain.yaml) adds optional `reader_hashes` (`ReaderHashCheck`) to `Answer`:
- `status` (`ReaderHashStatus`): `"green"` when the local reader verified the SHA-256 digest of every store object it read to build the answer against the manifest's pinned hashes, or `"unavailable"` if hash verification was not performed. (As fixed in [viewer-slip.md](viewer-slip.md), if any object's hash fails, the reader refuses to serve the publication rather than returning a `"red"` answer.)
- `checked_witnesses` (`WitnessHashCheck[]`, optional): one entry per conclusion on the page whose witness or calculation-witness proof piece was hashed and verified by the reader:
  - `conclusion` (`RowRef`): the derived row on the page;
  - `status` (`ReaderHashStatus`): `"green"` or `"unavailable"`;
  - `piece_sha256` (64 lowercase hex characters): the verified SHA-256 digest of the role's proof piece that supplied the witness.

Viewers quote `answer.reader_hashes` directly instead of fabricating `reader-hashes: green`.

### 4. `origin_sign` on served fact sources (`Source.origin_sign`)

[contracts/source.yaml](../contracts/source.yaml) adds enum `OriginSign` matching the four origin signs in [packs/std-view/key.yaml](../packs/std-view/key.yaml) and [contracts/view.yaml](../contracts/view.yaml) (`SignName`):
- `origin_decision` (`◆`)
- `origin_vendor` (`▲`)
- `origin_design` (`■`)
- `origin_observation` (`●`)

`Source` and `SourceRecord` gain an optional `origin_sign: OriginSign` attribute.
Pack authors declare `origin_sign` in `facts/<file>.sources.yaml` (on `default`, `records`, or `rows`).
The publisher preserves declared `origin_sign` verbatim in per-role `fact_sources` and `edge/gate/src/local.ts` serves it unchanged on `AnswerNode.sources`.
When a source does not declare `origin_sign`, it is omitted — neither the publisher, the reader, nor any viewer guesses an origin sign from `Source.kind`.

## Consequences

- **Contracts:** [contracts/explain.yaml](../contracts/explain.yaml) defines `TrustTier`, `ReaderHashStatus`, `ReaderHead`, `ReaderHashCheck`, `WitnessHashCheck`, and `Answer.reader_hashes`. [contracts/source.yaml](../contracts/source.yaml) defines `OriginSign` and optional `origin_sign` on `Source` and `SourceRecord`.
- **Implementation:** Follow-up worker PRs update `edge/gate/src/local.ts` (and `edge/publisher/` source-sidecar propagation for `origin_sign`) to lift the three strict `xfail` tests in `tests/slip/test_reader_seal_fields.py`.
- **Downstream viewers:** Once implemented and recorded in Rezono's slip tests, Cartouche's next pin bump unblocks `m2-seal-and-rights-from-rezono` without inventing any unserved field names.
