---
decider: [core, language]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: bitemporal-staircase-reading
---

# Bitemporal staircase reading of `std-time` and publishing `examples/zorgtoeslag-slice`

A bitemporal view shows how one subject's derived outcome changes across two independent time axes:

1. **Valid time (`valid_at` / `as_of`):** the dates or axis positions for which the rules evaluate what holds.
2. **Knowledge time (`known_at`):** the successive main epochs at which facts and parameter versions become recorded.

Consumers such as visualizers compute nothing themselves: they draw only rows, states, reasons, and witness references served through the local gate ([`edge/gate/src/local.ts`](../edge/gate/src/local.ts)). Today two gaps prevent serving a bitemporal staircase:

- `examples/zorgtoeslag-slice` has no `pack.yaml` or `README.md`, cannot yet compile or publish through `rezono_publisher`, and `rezono_publisher.batch.epoch` evaluates dated facts without an explicit `(as_of, known)` pair.
- `packs/std-time` declares shapes for its kinds in [`packs/std-time/channels.yaml`](../packs/std-time/channels.yaml), but declares no default bitemporal staircase reading, and `edge/gate/src/local.ts` has no reading route that serves a subject's verified `(valid_at, known_at)` cells with their canonical witness IRIs.

This decision defines:

1. publishing `examples/zorgtoeslag-slice` as a pack through `rezono_publisher`;
2. a generic, domain-free bitemporal history publishing helper in `rezono_publisher`;
3. the standard bitemporal staircase reading declared by `packs/std-time` (inherited by any `std-time`-bound pack, and declarable by any pack in `channels.yaml`);
4. the gate reading contract `GET /<pack>/<manifest>/readings/staircase` returning `rezono.staircase/1` with verified cells and canonical witness IRIs ([canonical conclusion and witness addresses](publication-conclusion-addresses.md)).

## 1. Publishing `examples/zorgtoeslag-slice` as a pack

[The first slice of the healthcare allowance](language-healthcare-allowance-slice.md) and [its three-source expansion](healthcare-allowance-three-sources.md) define the rules, cases (`allowance-cases.yaml`), and independent stdlib-only oracle (`reference.py`) of `examples/zorgtoeslag-slice`. To publish cleanly through `rezono_publisher`:

- `examples/zorgtoeslag-slice` carries `pack.yaml` (`name: zorgtoeslag-slice`), `README.md`, `channels.yaml`, labels, messages, and at least one filtered role (`reader`, via `may_read`) beside `checker` (`complete`).
- `rezono_publisher.batch.epoch(...)` accepts optional native ISO 8601 date parameters `as_of: str | None = None` and `known: str | None = None`. When supplied, dated facts (`facts.load(..., as_of=as_of, known=known)`) and calculation evaluation (`calc__as_of`) use those dates rather than failing or falling back to a fixed date. Integer `*_day` / `YYYYMMDD` fields are never introduced.
- Publishing `examples/zorgtoeslag-slice` with `batch.epoch` and `publish.publish` writes a manifest with a green `rezono:proofs` check, verified snapshots for `reader`, and verifiable calculation witnesses (`CalcWitness`) matching `reference.py`.

## 2. Generic bitemporal history helper in `rezono_publisher`

To publish a bitemporal series of main epochs into one store without coupling the publisher to any example domain:

- `rezono_publisher.history.publish_bitemporal_history(pack_dir, store_dir, roles, *, valid_dates, knowledge_dates, forms=False, sources=None)` is a domain-free helper.
- For each `(knowledge_date, valid_date)` pair in ascending knowledge-time then valid-time order (or one epoch per knowledge date when the pack itself carries multiple valid-time points per epoch), it publishes a verified main epoch `m-1`, `m-2`, ... into `store_dir` (`FileStore`) with `knowledge_time` derived from `knowledge_date` (ISO 8601 UTC timestamp) and `as_of=valid_date`, `known=knowledge_date`.
- It returns the list of published manifests (or summary with the latest manifest id) and never hardcodes any pack name, kind name, or subject id.

## 3. Standard staircase reading of `std-time`

Just as `packs/std-part/channels.yaml` declares a default `flows` reading (`id: parts`) for part-of hierarchies, [`packs/std-time/channels.yaml`](../packs/std-time/channels.yaml) declares the default bitemporal staircase reading under `staircases:` (schema in [`contracts/view.yaml`](../contracts/view.yaml)):

```yaml
staircases:
  - id: bitemporal
    title_message: staircase.bitemporal
    subject: interval
    relation: judgement
    valid_time_column: at
    state_column: value
    reason_column: reason
```

- **Default inheritance along `std-time`:** Any domain pack that imports `std-time` and binds a kind to `Interval` (via `is_a: Interval` or a `std-time` view) inherits `std-time`'s default `staircases` reading in its compiled `bundle/schema-bundle.json` (`channels.staircases`), rewritten to the domain's bound kind where mapped, without declaring `staircases:` itself.
- **Explicit declaration:** A pack that evaluates a bitemporal calculation rule (such as `allowance` over `calc__as_of.valid_at`, before `applies at` lowers) may declare a `staircases:` entry in its own `channels.yaml` naming its `subject` kind and outcome `relation` (with `valid_time_source: as_of` when valid time comes from `calc__as_of`).
- **No domain special cases:** Neither the compiler, nor the publisher, nor `edge/gate` hardcodes `zorgtoeslag-slice`, `Household`, `Persoon`, or `allowance`. Every decision is driven solely by `bundle.channels.staircases`, published snapshots, and published witnesses.

## 4. Gate reading contract (`rezono.staircase/1`)

[`edge/gate/src/local.ts`](../edge/gate/src/local.ts) serves the bitemporal staircase reading at:

```text
GET /<pack>/<manifest>/readings/staircase?subject=<id>[&reading=<id>]
```

- `<manifest>` is a main manifest id (`m-<n>`). The gate inspects readable main epochs from `m-1` up to `<manifest>` in ascending epoch order, enforcing `stillReadable(earlier, current)` and withdrawal rules (`410 Gone` with standing headers when an epoch or contributing row is withdrawn).
- `subject` is required (`400` if missing or empty). `reading` selects a `channels.staircases` entry by `id` (defaulting to the single declared staircase reading, or `"bitemporal"` when present; `404` if the pack declares no matching staircase reading).
- **Pure reader:** The gate computes no rules or domain formulas. It reads only the role-scoped snapshots and role-scoped witnesses (`witnesses` and `calc_witnesses`) already published in each readable epoch.
- **Response shape (`200 OK`, `format: "rezono.staircase/1"`):**

```json
{
  "format": "rezono.staircase/1",
  "pack": "<pack>",
  "manifest": "m-<n>",
  "reading": "<reading-id>",
  "subject": "<id>",
  "valid_times": ["<sorted distinct valid-time values>"],
  "knowledge_times": [
    {"manifest": "m-1", "epoch": 1, "knowledge_time": "<iso-timestamp>"}
  ],
  "cells": [
    {
      "manifest": "m-<k>",
      "valid_at": "<iso-date-or-reference-id>",
      "known_at": "<iso-timestamp>",
      "relation": "<relation>",
      "key": ["<canonical key parts>"],
      "state": "known|unknown|not_applicable|invalid|absent",
      "value": "<text-or-null>",
      "reason": "<reason-text>",
      "witness": {
        "sha256": "<64 lower-case hex>",
        "iri": "<base>witness/<64 lower-case hex>"
      }
    }
  ]
}
```

- **Explicit epistemic states:**
  - When a cell's outcome is known (for a calculation rule, `state == "known"`; for `std-time` `judgement`, any decided judgement value other than `"unknown"`), `state` is `"known"` and `value` carries the exact served value as text (never formatted or normalized).
  - When a cell's outcome is unknown (for a calculation rule, `state == "unknown"`; for `std-time` `judgement`, `value == "unknown"`), `state` is `"unknown"`, `value` is `null` (never `"0"` or an invented placeholder), and `reason` carries the exact published reason (e.g. `"no_version_applies"`, `"end_not_recorded"`).
- **Canonical witness references:** Every cell includes `witness.sha256` (the `canonical_sha256` of the published `Witness` or `CalcWitness` for that row in that epoch) and `witness.iri` (`<base>witness/<sha256>`, [canonical conclusion and witness addresses](publication-conclusion-addresses.md#2-canonical-witness-iris)), never `rezono:w/<sha256>`.
- **Role-scoped non-disclosure:** If the caller's role cannot read any cell for `subject` (either because `subject` does not exist or because the role's read rules exclude it), the gate returns the same `404` response (`missing()`), leaking neither existence nor values.

## 5. Considered alternatives

- **Hardcoding a healthcare-allowance endpoint in `edge/gate`.** Violates the domain-free core rule ([`AGENTS.md`](../AGENTS.md)) and would force a new endpoint for every future bitemporal domain.
- **Computing the staircase grid in a viewer from raw fact files.** Violates the rule that viewers compute nothing and read only verified gate outputs.
- **Serving unverified rows without witness IRIs or with `rezono:w/` URIs.** Breaks provenance linking and leaves publication `$why`, `prov.ttl`, and gate readings naming the same witness with two different IRIs.

## 6. Red tests

All tasks are recorded as strict `extra:` red tests:

1. `examples/test_zorgtoeslag_staircase.py::test_zorgtoeslag_slice_compiles_and_publishes_via_publisher`: verifies `examples/zorgtoeslag-slice` is a valid pack (`pack.yaml`, `README.md`), compiles cleanly, publishes via `rezono_publisher.batch.epoch` and `publish.publish` with green proofs matching `reference.py`, and is served by `edge/gate/src/local.ts`.
2. `tests/slip/test_bitemporal_staircase_reading.py::test_std_time_bound_pack_serves_bitemporal_staircase_reading_via_gate`: verifies on a neutral, domain-free `std-time`-bound pack that `packs/std-time` supplies the default staircase reading and `edge/gate/src/local.ts` serves `GET /<pack>/<manifest>/readings/staircase` with verified cells, explicit `unknown` vs `known` states, canonical `<base>witness/<H>` IRIs, and role-scoped `404` non-disclosure.
3. `examples/test_zorgtoeslag_staircase.py::test_zorgtoeslag_slice_bitemporal_staircase_served_via_gate`: verifies `rezono_publisher.history.publish_bitemporal_history` + `edge/gate/src/local.ts` serve the bitemporal staircase of `examples/zorgtoeslag-slice` across valid months and knowledge days, agreeing with `reference.py` for `bob`/`p-bob` (`unknown` before `2025-12-01`, `10500` after) and `gus`/`p-gus` (`13500` before `2026-04-15`, retroactive `8500` after) with verified canonical witness IRIs (waits for tests 1 and 2).
