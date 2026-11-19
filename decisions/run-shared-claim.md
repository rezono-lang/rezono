# A shared write-once claim for a live run

The offline journal claim is a SQLite row. It proves single acquisition only for as long as one file lives. A live run starts on a fresh runner, so its claim must outlive the runner and be visible to every later attempt. The [offline acceptance decision](run-offline-acceptance.md) and the [operator guide](../run/OPERATOR.md) leave that backend open.

## Decision

Store the live claim as a Git reference in the repository that holds the approved plan. The reference is `refs/rezono/run-claims/<plan hash>`. Creating it is the single write that can succeed once. Git already gives the property we need: a push with `--force-with-lease=<ref>:` (an empty expected value) succeeds only while the reference does not exist, and the remote applies it atomically under its reference lock.

`run/git_claim.py` exposes two functions with the same shape as the offline claim.

| Function | Contract |
| --- | --- |
| `claim_once(remote, plan_hash, run_id) -> bool` | Validate a 64-character lowercase hexadecimal plan hash and a run ID of letters, digits, `.`, `_` and `-`; otherwise raise `ValueError`. Create a commit with the empty tree and the exact message `run-claim <plan hash> <run id>`. Use a fixed author and committer identity without a personal address and Unix time 0 in UTC (Git date `@0 +0000`) for both, so identical arguments give the identical commit ID. Push it to the reference with an empty lease. Return `True` only when this push created the reference. Because the commit is deterministic, a repeat with identical arguments pushes the commit the reference already holds; Git then reports the reference as up to date and exits successfully without checking the lease. That is not a creation: read the per-reference status, for example from `git push --porcelain`, where a created reference is marked `*`. When the push fails, list the remote reference: if it exists, return `False`; if the listing fails or the reference is absent, raise `RuntimeError`. Never return `False` for an unreachable remote. |
| `holder(remote, plan_hash) -> str \| None` | Return the run ID recorded in the claim commit message, or `None` when the reference is absent. Raise `RuntimeError` when the remote cannot be read or the message does not have the exact form above. |

Every later call returns `False`, including one from the run that holds the claim. A restarted attempt therefore never dispatches again; it resolves the order through status with the plan hash as key, as the order-uncertainty boundary already does. A claim is never deleted by the run. Removing one is a recorded operator action, outside this boundary.

The protected run workflow is the only writer. Its job needs `contents: write` for this reference namespace and nothing else from the repository. Before the first live use, verify that the hosting service accepts a reference in `refs/rezono/`. If it does not, use `refs/tags/run-claims/<plan hash>` with the same lease; the semantics do not change.

## Alternatives

A Kubernetes `Lease` or `ConfigMap` create is also atomic, but no cluster exists before the run builds one, and a cluster built by the run cannot hold the claim that guards its own order. An object store with a conditional create would add an account, a credential and a paid service. A file in the run's workspace dies with the runner. A Git reference adds no service, survives every runner, and keeps the claim beside the plan it guards, reviewable with ordinary Git tools.

## Test

`run/tests/test_git_claim.py` uses a local bare repository. Six concurrent callers with distinct run IDs give exactly one `True`. The holder is the winner, the remote has exactly one claim reference, and its message names the winner. A fresh import returns `False` for the winner's own repeat. Another plan hash is independent. The same arguments against a second remote give the same commit ID. A missing remote raises instead of reporting a consumed claim.
