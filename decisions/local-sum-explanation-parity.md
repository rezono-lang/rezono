---
decider: [core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: local-sum-explanation-parity
---

# Local explanation parity for published aggregate sums over value columns

## Context

In [contracts/rules.yaml](../contracts/rules.yaml) and [contracts/fixtures/rules/RuleProgram/valid/aggregates.yaml](../contracts/fixtures/rules/RuleProgram/valid/aggregates.yaml), a relation may carry value columns outside its primary key — for example `hours(member, task; h)` where `key` is `[member, task]` and `values` is `[h]`, aggregated by `member_hours(member, total)` via `sum` over `h`.

The publisher (`edge/publisher/rezono_publisher/proof.py`, `engine_rows` + `trace.steps(..., valued=True)`) and the independent checker (`checker/rezono_checker/proof.py` and `checker/rezono_checker/check.py`) already read `values` alongside `key` from snapshot records (`{"key": [...], "values": {"h": {"state": "known", "value": "..."}}}`), emit each `contributes` proof step with its contributing value (`"known:<cell>"`), and verify the aggregate witness's `contributors_sha256` over the sorted `[premise_key, contribution_value]` pairs.

However, the local reader's "Why?" route (`GET /<pack>/<manifest>/ask/<question>` in `edge/gate/src/local.ts`, `named`) currently reconstructs `step` rows by passing only `(await view.rows(name)).map((row) => row.key)` into `stepsOf` (`edge/gate/src/ask.ts`), where `RuleDoc` declares only `key` columns and rejects any `sum`, `min`, or `max` whose `over` column lies in `values` outside `key`. Opening a published archive locally therefore fails with HTTP `500` instead of serving the same explanation that the role's published proof steps hold.

## Decision

Opening the exact same published archive with the exact same role locally (`edge/gate/src/local.ts`) and via the role's published proof steps (`rezono_publisher.proof.plan`, verified by `rezono_checker.proof.check_proof`) must produce the exact same explanation for aggregate sums (and `min` / `max`) over value columns outside the key:

1. **Identical tasks, contributing values, and proof hash:** For every visible aggregate conclusion (such as `member_hours(member, total)` over `hours(member, task; h)`), `GET /<pack>/<manifest>/ask/<question>` returns HTTP `200` with the exact same contributing rows (`steps` with `how: "contributes"`), the exact same contributing value text (`value: "known:<cell>"` read from the value column outside the key), and the exact same witness `contributors_sha256` proof hash as the role-published proof steps.
2. **Two admissible implementations (same observable contract):** The local gate may satisfy this contract either by:
   - reading the role's verified published proof trees (`<pack>/<manifest>/<role>/views/index.json` -> `proof/witness`, `proof/back`, `proof/forward`, checking every piece's SHA-256 against its parent index/page) directly when present; OR
   - reconstructing proof steps locally in `edge/gate/src/local.ts` and `edge/gate/src/ask.ts` using the identical inputs and checks as `rezono_publisher.proof.engine_rows` + `rezono_compiler.trace.steps`:
     - read `values` column definitions on `RuleDoc.relations`,
     - forward snapshot `values` alongside `key` into `stepsOf`,
     - extract `known:` value text from `row.values[over]` (supporting `value` and `minor_units` when `state === "known"`), and
     - fail closed (never fabricate `known:` or coerce to `0`) if any contributing cell is missing or not in state `"known"`.
3. **No unverified fallback:** Whichever path runs, hash verification of all read store objects against the manifest remains mandatory (`decisions/reader-served-seal-fields.md`), and role boundaries stay strictly enforced.

## Acceptance

`edge/gate/test/test_local_sum_explanation_parity.py` builds a real verified publication from `contracts/fixtures/rules/RuleProgram/valid/aggregates.yaml` (`hours(member, task; h)` -> `member_hours(member, total)`), verifies its witnesses and published proof trees with `rezono_checker.check.check` and `rezono_checker.proof.check_proof`, opens the exact same publication with the exact same role (`reader`) via both the published proof steps and `openLocalGate`, and asserts that each member's sum returns the exact same contributing tasks, hours (value column outside the key), and `contributors_sha256` proof hash.
