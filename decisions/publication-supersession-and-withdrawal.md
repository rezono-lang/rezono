---
decider: [core]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: publication-supersession-and-withdrawal
---

# Publications are superseded, never deleted, and withdrawn by decision

A published epoch in Rezono is an immutable record: its manifest ([contracts/manifest.yaml](../contracts/manifest.yaml)), its head pointer, its snapshots and its role epoch statement ([contracts/statement.yaml](../contracts/statement.yaml)) are written once and verified by content hash. In [`std-decision`](../packs/std-decision/README.md), an older decision is never erased or rewritten to mark that a newer decision replaced it; replacement is derived from newer decisions (`replaced` and `in_force_on`), and taking a decision back without replacement is recorded explicitly as `withdrawn` ([decision schema](../packs/std-decision/schema/decision.yaml)).

Publications follow the same principle. Old published manifests remain permanently citable and immutable; supersession is derived from newer manifests rather than written into the old manifest; and withdrawal is recorded as an immutable decision fact that causes the HTTP reader ([local gate](../edge/gate/src/local.ts)) to answer with HTTP `410` (Gone) and the withdrawal reason.

## 1. Immutability and derived supersession

- A published main manifest (`<pack>/manifests/m-<epoch>.json`), its head pointer (`<pack>/heads/<10^19 - 1 - epoch>.json`) and its referenced objects are never modified or overwritten when a newer epoch is published.
- Whether a published main manifest `m-<e1>` has been superseded is derived solely from the existence of a newer main manifest `m-<e2>` (`e2 > e1`, discovered through `<pack>/heads/`). No `"superseded"` field is ever written into `<pack>/manifests/m-<e1>.json`.
- Citing an earlier main manifest remains readable as long as the caller's current read authority still covers it ([central read access](central-read-access.md#5-historical-manifest-readability-in-the-local-gate-stillreadable)) and the requested epoch or row has not been withdrawn.
- When the HTTP reader serves a response pinned to an earlier main manifest `view` (`view.manifest.epoch < current.manifest.epoch`), it returns HTTP `200` with the exact retained response body and adds the derived supersession headers:
  - `x-rezono-standing: superseded`
  - `x-rezono-superseded-by: <current.manifest.id>`
  - `link: </<pack>/manifests/<current.manifest.id>>; rel="successor-version"`
- When the HTTP reader serves the current (newest, non-withdrawn) main manifest, it returns HTTP `200` with `x-rezono-standing: current` and no `x-rezono-superseded-by` header.

Carrying derived standing in response headers keeps stored manifest bytes, head hashes, epoch statements and retained JSON response bodies byte-identical after newer epochs publish.

## 2. Withdrawal as a decision fact

Withdrawing a published epoch or row never deletes or edits the published manifest, its head or its objects. Instead, withdrawal is recorded as a write-once decision document in its own namespace under the pack store:

```text
<pack>/withdrawals/<id>.json
```

Each withdrawal document is canonical JSON with the following fields, aligned with `Decision` in [`packs/std-decision`](../packs/std-decision/schema/decision.yaml):

| Field | Required | Meaning |
| --- | --- | --- |
| `format` | yes | `"rezono.withdrawal/1"` |
| `id` | yes | safe slug `^[A-Za-z0-9][A-Za-z0-9._-]*$`, matching `<id>.json` |
| `state` | yes | `"withdrawn"` |
| `decider` | yes | non-empty list of non-empty strings naming who withdrew the publication part |
| `decided_on` | yes | ISO calendar date `YYYY-MM-DD` when the withdrawal decision was taken |
| `reason` | yes | non-empty trimmed text stating why the publication part was withdrawn |
| `epochs` | at least one of `epochs` or `rows` non-empty | list of main manifest ids (`m-<epoch>`) withdrawn in full |
| `rows` | at least one of `epochs` or `rows` non-empty | list of row targets `{"relation": "<relation>", "key": ["..."], "manifest": "m-<epoch>"}` (`manifest` optional: when present, withdraws the row in that epoch; when omitted, withdraws the row across all epochs of the pack) |

- An anonymous withdrawal (empty `decider`) or a withdrawal without a reason (empty or whitespace-only `reason`) is refused.
- A publisher helper (`edge/publisher/rezono_publisher/withdraw.py`, `record_withdrawal(store, pack, record)`) validates the record and writes `<pack>/withdrawals/<id>.json` using conditional `put_new` (conflicting bytes for an existing id raise `store.Conflict`) without modifying any manifest or head.
- The collector (`edge/publisher/rezono_publisher/collect.py`) treats `<pack>/withdrawals/` as a permanently retained namespace and never deletes withdrawal records, so a withdrawn epoch stays `410` (Gone) rather than silently becoming `404` (Not Found).

## 3. HTTP reader behavior on withdrawal

When the HTTP reader (`edge/gate/src/local.ts`) handles a request for pack `<pack>`:

1. Confirm that `current` exists for the caller's role first; an unauthorized role that cannot read the pack still receives `404` and learns nothing about hidden packs or withdrawals.
2. Load all records under `<pack>/withdrawals/`. If any record fails to parse or violates section 2, fail closed with HTTP `500` (`invalid publication`) so a corrupt withdrawal record can never serve withdrawn data.
3. **Withdrawn epoch:** If any withdrawal record lists the resolved manifest id in `epochs` (including when the newest head itself is withdrawn), respond to every route on that manifest (`/<pack>/manifests/<id>`, `/<pack>/head?m=<id>`, `/<pack>/head`, `/<pack>/bundle?m=<id>`, `/<pack>/<id>/snapshots/...`, `/<pack>/<id>/rows/...`, `/<pack>/<id>/ask/...`) with:
   - HTTP status **`410`** (Gone)
   - Headers: `cache-control: private, no-store`, `x-rezono-standing: withdrawn`
   - JSON body:

   ```json
   {
     "error": "withdrawn",
     "reason": "<reason>",
     "withdrawal": {
       "id": "<id>",
       "decider": ["<party>"],
       "decided_on": "YYYY-MM-DD",
       "reason": "<reason>"
     }
   }
   ```

   Epoch withdrawal is checked before `stillReadable`, so citing a withdrawn epoch returns `410` with its reason even after later schema or data changes. When multiple withdrawal records cover the same target, the reader deterministically selects the record with the lexicographically smallest `id`.
4. **Withdrawn row:** If any withdrawal record targets a row `(relation, key)` in the requested epoch (or across all epochs), a direct request for that row (`ask/<term>`, `POST ask` with `scope: "row"`, `rows/<relation>` matching that key) or any collection read touching the affected relation in that epoch responds with HTTP `410` and the same body and headers. The reader fails closed rather than silently dropping withdrawn rows from a closed snapshot, which would turn a withdrawn fact into a false absence.
5. Non-withdrawn epochs of the same pack remain readable as usual.

## Alternatives considered

- **Rewrite old manifests in place with a `"superseded": true` or `"withdrawn": true` field.** Mutating a published manifest breaks its content hash, invalidates its head pointer and signed epoch statement, and violates write-once storage.
- **Delete withdrawn manifests from the store.** Deleting a manifest turns citations into `404` (Not Found), erasing both the audit trail of who withdrew it and the reason why it was withdrawn.
- **Silently omit withdrawn rows from snapshot responses.** In a closed-world relation, silently omitting a row changes the logical meaning of absence; returning HTTP `410` with the withdrawal reason preserves soundness.
- **Embed `"superseded": true` in the JSON body of `GET /<pack>/manifests/<id>`.** Changing the JSON body of an immutable manifest after a later epoch is published breaks byte-identical retained recordings; HTTP response headers (`x-rezono-standing`, `x-rezono-superseded-by`, `link`) communicate derived standing cleanly on every route without mutating the payload.
