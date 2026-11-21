---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: bitemporal-history-publication
---

# Publish successive `(as_of, known)` main epochs into one store

A bitemporal sheet (such as a valid-time by knowledge-time staircase for a household's healthcare allowance in [the healthcare allowance slice](language-healthcare-allowance-slice.md)) compares conclusions across distinct `(as_of, known)` pairs without computing anything on the client ([one structure space and readings](one-structure-space-and-readings.md)). Each `(as_of, known)` pair is published as a sealed main epoch (`m-1`, `m-2`, ...) into the same publication store, so `edge/gate` serves the full history read-only through existing `/head?m=m-<n>` and `/m-<n>/rows/<relation>` routes.

## 1. Multi-epoch publication of a dated pack

For a sequence of `(as_of, known)` evaluation points `[(as_of_1, known_1), ..., (as_of_k, known_k)]`:

1. Each point `i` (`1 <= i <= k`) resolves the pack's dated facts at `(as_of_i, known_i)` (`decisions/language-dated-facts.md`) and evaluates the pack's calculation at `as of <as_of_i> known <known_i>`.
2. Each point publishes as main epoch `epoch = i` (`manifest = m-<i>`) with `knowledge_time = "<known_i>T00:00:00Z"` into one shared `FileStore` (`edge/publisher/rezono_publisher/batch.py` + `publish.py`).
3. Every published epoch is checked independently by `rezono_checker` (`witness_check: green`) and written under `<pack>/heads/` and `<pack>/manifests/m-<i>.json`.

### 1.1 Dated-slot totality checks

In Rezono calculations, optional (`?`) slots map missing values to `not_applicable`, whereas required slots map missing values to `unknown` (`docs/rezono/v0.md`). A slot populated by dated `FactRow` declarations (`decisions/language-dated-facts.md`) therefore stays required so that dates before the first reported version yield explicit `unknown` (`no_version_applies`), rather than `not_applicable`.

Because an `(as_of, known)` epoch legitimately omits rows for records that have no active dated version on that date, `rezono_publisher.batch.epoch` accepts an explicit, declared check parameter `dated_totality: Literal["red", "warning"] = "red"`:

- **Default (`dated_totality="red"`):** Every totality check violation stays `"red"` and blocks publication. Nothing is silently downgraded.
- **Explicit `(as_of, known)` bitemporal epoch (`dated_totality="warning"`):** Permitted only when both `as_of` and `known` are supplied (failing closed with `Blocked` otherwise, or on any other parameter value). Only totality checks (`<kind>__<slot>__totality`) whose table `<kind>__<slot>` is populated by dated `FactRow` declarations (`dated_tables`) are recorded as `status: "warning"` with their exact `violations` count preserved. All non-dated totality checks and every other schema/rule check remain `"red"`.

## 2. Read-only serving via `edge/gate`

Readers (such as Cartouche) query the shared store exclusively through `edge/gate/src/local.ts`:

- `GET /<pack>/head` returns the latest manifest (`m-<k>`).
- `GET /<pack>/head?m=m-<i>` returns the verified historical manifest for epoch `i` (carrying its `knowledge_time`, `witness_check`, and snapshot digests).
- `GET /<pack>/m-<i>/rows/<relation>` returns the verified calculation snapshot rows for epoch `i` (including explicit four-valued `state` such as `known` vs `unknown` without collapsing `unknown` to `0`).

No new gate route, client-side derivation, or mutable state is introduced: the store already holds the immutable, checker-verified bitemporal history, and `edge/gate` projects it verbatim.
