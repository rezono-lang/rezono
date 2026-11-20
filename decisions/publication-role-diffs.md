---
decider: [core, platform]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: publication-role-diffs
---

# Compute role-scoped epoch diffs from each role's own snapshots and chain epoch statements

Each filtered role reads a publication of its own ([vision](../docs/vision.md#access)). Today, [the difference step](../edge/publisher/rezono_publisher/difference.py) compares one role's own snapshots for proposals and variants (`p-…`, `v-…`) against a main `base_manifest`, while [the publication form builder](../edge/publisher/rezono_publisher/forms.py) writes an independent [epoch statement](../contracts/statement.yaml) (`rezono.epoch-statement/1`) per main epoch without linking consecutive epochs or publishing an epoch-to-epoch diff for each role.

As Rezono prepares for live incremental updates (for example via Feldera), readers need verifiable, role-scoped diffs between consecutive main epochs and a cryptographic chain linking each role's epoch statement to its predecessor — without ever breaking non-interference or changing published contracts later.

## 1. Diff a role's own snapshots only — never filter a whole-publication diff

A role's diff between two epochs is **always** computed by comparing **that role's own two snapshot sets** (the role's snapshots in its immediately preceding published main epoch and the role's snapshots in the current main epoch).

A publisher or engine MUST NEVER compute a whole-publication diff over complete snapshots and filter it per role afterwards. Filtering a whole-publication diff can leak unreadable rows through:

- **Ordering and pairing:** cell-change pairing or row ordering derived from a complete diff can depend on rows the role cannot read.
- **Timing:** filtering work scales with changes in unreadable rows.
- **Diff size and presence:** non-empty diff metadata, counts, chunk boundaries, or changed diff hashes can reveal that unreadable rows changed even when the role's readable state did not change.

By computing the diff strictly from the role's own snapshot bytes — reusing the deterministic row comparison in `rezono_publisher.difference.entries` and verifying it independently with `rezono_checker.difference.changes` — the diff obeys the same non-interference guarantee as the role's publication form: two worlds that differ only in rows a role cannot read produce byte-for-byte identical diffs.

The complete role (`complete: true`) never receives a publication form, a role-scoped epoch diff, or an epoch statement.

## 2. The role-scoped epoch diff object (`diff.json`)

When a filtered role (`complete: false`) has an immediately preceding main epoch publication (the latest earlier main manifest with `epoch < current.epoch` — or `base_manifest` when present — that includes that role and holds a published `statement.json` for that role), [the form builder](../edge/publisher/rezono_publisher/forms.py) computes and writes one canonical diff object under the role's publication prefix:

```text
<pack>/<manifest>/<role>/publication/diff.json
```

Its canonical JSON payload (RFC 8785 / sorted keys, compact UTF-8, no trailing whitespace, every value text or lists/objects of text) has format `rezono.role-diff/1`:

```json
{
  "format": "rezono.role-diff/1",
  "relations": {
    "<relation>": [
      {"change": "added", "key": ["..."]},
      {"change": "changed", "key": ["..."], "was": ["..."]},
      {"change": "removed", "key": ["..."]}
    ]
  }
}
```

- **Row semantics:** Each relation's entry list is the exact output of `rezono_publisher.difference.entries(before_bytes, after_bytes)` sorted by `key`, using the same `added`, `removed`, and single-valued cell `changed` (with `was`) rules as proposal and variant diffs.
- **Unchanged relations omitted:** Any relation whose snapshot did not change for that role is omitted from `relations`. When nothing readable to the role changed between the two epochs, `relations` is `{}` and the canonical bytes are always exactly:

  ```json
  {"format":"rezono.role-diff/1","relations":{}}
  ```

- **Pure content, no epoch envelope:** `diff.json` deliberately omits manifest IDs, epoch numbers, and timestamps. The epoch link lives in `statement.json`. Consequently, every empty diff for any role has one constant canonical byte sequence and one constant SHA-256 hash.
- **Independent verification (fail closed):** Before writing any object or index for the role, the publisher recomputes each relation's diff with `rezono_checker.difference.changes` over the role's previous and current snapshot bytes. Any mismatch raises `Blocked` and writes nothing.
- **Initial epoch:** When a role has no prior main epoch publication (first publication of the pack, or first epoch in which the role appears), no `diff.json` is written.
- **Form index and subject list:** On chained epochs, `diff.json` is listed in `<pack>/<manifest>/<role>/publication/index.json` (subject to the `FORM_OBJECTS` limit) and in `statement.json`'s `subject` list with its SHA-256 digest.

## 3. Epoch statement v2 (`contracts/statement.yaml`) and the per-role chain

[The statement contract](../contracts/statement.yaml) preserves version 1 (`predicateType: "https://rezono.org/epoch-statement/v1"`, `format: "rezono.epoch-statement/1"`) untouched so previously sealed and archived publications remain verifiable without modification.

Version 2 of the epoch statement (`predicateType: "https://rezono.org/epoch-statement/v2"`, `format: "rezono.epoch-statement/2"`) keeps every field of version 1 — still using text for every leaf value so Rezono's canonical bytes remain identical to RFC 8785 — and adds two optional epoch-chain fields to `EpochPredicate`:

| Field | Type | Presence | Meaning |
| --- | --- | --- | --- |
| `previous` | `Sha256` | Chained epochs only | SHA-256 of the canonical `statement.json` bytes of this same role's immediately preceding main epoch publication |
| `diff` | `Sha256` | Chained epochs only | SHA-256 of this role's canonical `diff.json` bytes for the transition from that previous epoch to this epoch |

Rules for `previous` and `diff`:

1. **Both or neither:** A role's initial epoch statement omits both `previous` and `diff` (never empty-string placeholders). Every subsequent main epoch statement for that role carries both `previous` and `diff`.
2. **Same-role chain:** `previous` always links to the prior `statement.json` of the **same pack and same role** with a strictly smaller `epoch`. It never references another role's statement or a complete manifest.
3. **Subject agreement:** On a chained statement, `diff.json` MUST appear in `subject` with a `digest.sha256` equal to `predicate.diff`.
4. **Verifier check (`rezono_publication.statement.verify`):**
   - Verifies v2 shape (closed at every level, both `previous` and `diff` present together or absent together, all leaf values text) and verifies that `diff.json`'s bytes match both `subject` and `predicate.diff`.
   - When given the predecessor's `statement.json` and snapshot bytes, verifies that `sha256(previous_statement_bytes) == predicate.previous`, that `pack` and `role` match with `int(prev.epoch) < int(curr.epoch)`, that recomputing the diff from the role's previous snapshots to the role's current snapshots reproduces `diff.json` byte for byte, and that applying `diff.json` to the previous snapshots yields the current snapshots.

## 4. Non-interference and readiness for live incremental updates

Suppose a pack publishes main epochs `m-1`, `m-2`, and `m-3` for two filtered roles `A` and `B`, where the changes in `m-2` and `m-3` affect only rows readable by role `A`:

- Role `A`'s `diff.json` in `m-2` and `m-3` is non-empty and records only role `A`'s snapshot changes.
- Role `B`'s `diff.json` in `m-2` and `m-3` is empty (`{"format":"rezono.role-diff/1","relations":{}}`).
- Role `B`'s `predicate.snapshots`, `schema`, `dataset`, `annotation`, `roots`, `inclusion`, `definition`, and every non-diff data subject (`schema.json`, `rows.json`, `hashes.json`, columnar tables, standards exports) stay identical across `m-1`, `m-2`, and `m-3`.
- Comparing `m-1` to `m-2`, role `B`'s `statement.json` changes **only** in the epoch-chain / manifest-envelope fields (`manifest`, `epoch`, `knowledge_time`, `role_manifest`, `previous`, and `diff` entering on the first chained epoch).
- Comparing `m-2` to `m-3`, role `B`'s `diff.json` and `predicate.diff` also remain identical — **only** `manifest`, `epoch`, `knowledge_time`, `role_manifest`, and `previous` advance the chain.

Because the published contract binds the exact role-scoped diff bytes (`diff.json`) and chains consecutive statements per role (`previous`), a future live incremental backend (such as Feldera) can stream per-epoch role updates and emit the exact same `diff.json` and v2 `statement.json` chain without changing any published contract or verifier.

## 5. Considered alternatives

- **Filtering a whole-publication diff per role.** Rejected: risks leaking unreadable rows through ordering, cell-pairing interactions, timing, or diff metadata/size. Diffing each role's own two snapshots makes non-interference structural.
- **Embedding `manifest` and `base_manifest` inside `diff.json`.** Rejected: an empty diff would change its bytes and hash on every unchanged epoch even when nothing readable changed. Keeping epoch metadata in `statement.json` makes every empty diff hash to one constant digest.
- **Mutating `rezono.epoch-statement/1` in place.** Rejected: v1 explicitly closes its field set and refuses `previous` so archived/sealed publications stay immutable. Moving to v2 preserves backward verification of all v1 statements.
- **Writing empty string placeholders (`previous: ""`, `diff: ""`) on the first epoch.** Rejected: violates the contract's `Sha256` pattern and echoes the placeholder antipattern already refused in v1.

## 6. Tests

- [edge/publisher/tests/test_role_epoch_diffs.py](../edge/publisher/tests/test_role_epoch_diffs.py):
  - `test_role_epoch_diff_is_empty_and_statement_changes_only_chain_fields_on_other_role_change`: publishes three consecutive main epochs (`m-1`, `m-2`, `m-3`) with two filtered roles (`role_a`, `role_b`) where `m-2` and `m-3` change only rows readable by `role_a`. Verifies that `role_a`'s `diff.json` captures only `role_a`'s changes, `role_b`'s `diff.json` is empty, `role_b`'s `statement.json` chains `previous` to `role_b`'s prior statement hash and records `diff`, and `role_b`'s statement changes **only** in the epoch-chain fields — never in snapshot hashes, dataset/root hashes, or diff contents.
