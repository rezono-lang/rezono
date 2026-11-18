# External run evidence

The run consumes external evidence at the boundaries of the existing loop.
Keep policy in rules and provider I/O in the declared ports. A provider's
response, an operator's decision, and a clock observation have different
origins. None may substitute for another. Reuse EffectPlan, EffectApply,
Observation, Source and RowRef. Do not define another executor or journal.

## Offline input records

Use one closed Draft 2020-12 JSON Schema per raw input record under
`run/schemas/`. Reject unknown fields at every object level. These schemas
describe synthetic replay inputs and adapter output. They grant no permission.

| Schema file | Required data | Constraints |
| --- | --- | --- |
| `approval.json` | `plan_hash`, `budget_cents`, `currency`, `expires_at`, `decision` | Use the exact EffectPlan digest and currency formats, a nonnegative integer amount, a real UTC instant ending in Z, and the choice `approve` or `decline`. |
| `inventory-page.json` | `sweep_id`, `page_id`, `next_page_id`, `resources` | IDs are nonempty strings. Only the final page has a null successor. Every resource has exactly an `id` and a `plan_hash`. The hash can be null for an untagged resource. No duplicates within a page. |
| `offer.json` | `sku`, `currency`, `period_seconds`, `period_price_micros`, `setup_price_micros`, `source_sha256` | SKU is nonempty, the billing interval is a positive integer, prices are nonnegative integer millionths of one currency unit, and the digest identifies the source bytes. |

Use the UTC instant and digest syntax of the repository contracts. A JSON
Schema consumer enables date-time format checking. Reject newline suffixes
in currency and digest fields. A list price is a source-backed observation.
Taxes, storage, traffic, minimum terms and setup charges affecting a real quote
must all be recorded before a provider can be selected. The offer record is
one priced line item and cannot establish a complete quote.

## Evaluation boundaries

Compare approved and computed spend in exact integer or rational arithmetic.
Allow equality at the ceiling. An event at or after expiry cannot authorize a
dispatch. Match currency and plan hash exactly. A protected environment
supplies independent human approval at deployment time.

Prove inventory completion from a chain rooted in the requested first page.
Every successor must be present once in the same sweep and the chain must end.
A timeout, a cycle, or a missing page yields unknown status. Derive absence
only after a complete sweep with no matching plan hash. The cleanup pack
joins the recorded delete dispatch and sweep start on attempt ID, run, scope
and plan digest. The start must be strictly later than dispatch. Legacy
coverage reports remain readable and cannot establish completeness.

The inventory adapter projects each page response independently. A null
successor is recorded as the empty string, which cannot be a page token.
The source array length and tagged or explicitly untagged item rows travel
with the page. The rules check the rooted chain and all of its item counts.
Cleanup evidence names the dispatch, sweep, terminal and contributing pages.

The alternative of using a single provider-specific order document as plan,
approval and cleanup proof loses the independence of these observations.

- [EffectPlan and EffectApply](../contracts/effect.yaml)
- [Observation](../contracts/observation.yaml)
- [Source](../contracts/source.yaml)
- [Run-scoped reconciliation](loop-design.md)
