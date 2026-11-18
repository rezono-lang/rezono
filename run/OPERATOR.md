# Preparing an operator-triggered run

Offline acceptance uses the local request file, recorded provider responses,
and a throwaway journal. It requires no account. Live ordering remains gated
on a complete independently verified quote, supported installation and a
shared durable claim store. The offline price fixture contains two observed SKU rates and does not authorize a purchase.

| Order | Operator action | Evidence to retain |
| --- | --- | --- |
| 1 | Open the provider account and set a low resource quota. | Account scope and quota observation. |
| 2 | Provision the read-only identity for live preflight in the protected environment. | Reference and verified ability to read price, inventory and stock. |
| 3 | Provision a separate execution identity restricted to the target account and resource scope. | Reference, permission scope and access to independent cleanup inventory. |
| 4 | Set the currency, maximum spend and a UTC expiry on the proposed plan. Include all applicable charges, billing terms and the same-day cleanup deadline. | Exact quote, source digests, immutable plan digest and read-only comparison. |
| 5 | Configure the protected run environment with a required operator reviewer. Verify the runner can use a durable journal and that same-day cleanup and quota enforcement are in place. | Environment review policy, durable storage configuration and cleanup arrangements. |
| 6 | Review the exact plan and its preflight findings, then approve and manually start the protected workflow from main when the installation gates have passed. | Decision bound to the plan digest, currency, ceiling and expiry. |
| 7 | Verify committed request, observed delivery, deletion and a complete provider inventory containing no resources tagged with the plan. | Request commit, readiness evidence, paginated inventory sweep and final cost. |

A price change, unknown stock, missing required observation or expired approval
requires a new review. A timed-out order goes to status under its consumed key.
Do not retry the purchase as a fresh order to resolve a lost response.

The preflight workflow design accepts a pinned plan from main on manual
dispatch, grants repository contents read access only, and binds exclusively
to the read-only identity. It emits observed price, stock and source evidence
and fails closed on drift or unavailable data. The run workflow separately
requires its protected environment and a manual main-branch trigger. The
workflow owner must wire these entry points once the respective ports exist.
