# Tenant proposal inputs and derived evidence

The operator preview uses the same request files as the portal. The three derived results below are production pack relations returned by the public request preview's `relation NAME` command. The pack consumes typed catalog and proposal inputs. Its adapter only converts declared fields to typed records. A proposal cannot grant itself review authority or read access.

In the trusted catalog, `reviewGrants` lists pairs of reviewer and action. `decisionsByReviewer` lists objects containing reviewer, sourceDelivery, target and port. Only a reviewer granted `approve-connection` can authorize that exact direction, target and port. `readableQuotas` contains objects with id, owner, dimension and amount. These represent independently issued tenant-readable quotas. Both new decision tables and the quota table default to empty. Treat the existing catalog's published capacities, resource vectors, zone matrix, profile zones and item provisions as ordinary input facts. Apply the same request conversion to every submitted team/service path. Extend the adapter only once, after the public input adapter is available.

| Production result | Columns |
| --- | --- |
| tenant_resource_capacity | pool, dimension, landed usage, limit |
| tenant_resource_shortage | pool, dimension, positive shortage |
| tenant_connection_review | team, delivery, target, port, decision, reason |
| tenant_delivery_component_evidence | reader, delivery, part, component, request item ID |
| tenant_quota_evidence | reader, owned request item ID, quota ID, requested cores, quota amount |

Cross-tenant connections need the peer's matching request and an authorized decision in addition to zone policy. A tenant-visible delivery component must have a readable request item as its witness. A tenant-visible quota comparison must have a readable grant for both its item and its own quota. Results carrying another tenant's quota or input use are forbidden, even when they support a numerically equivalent result. The operator's complete proposal comparison contains distinct rows for each reader. Ordinary tenant publications enforce the same reader scope. The independent fixtures cover landed capacity and candidate shortfalls, authority and potential disclosure; the portal renders their results.


## Capacity on the combined proposal

The trusted base catalog supplies `landedDeliveries`, the currently effective receipts.
Each records the stable request identifier (team/service), the full immutable merge revision,
and its charged cores, memoryGiB and storageGiB. Use the request identifier as the key of
`tenant_landed_delivery` and retain the revision as a witness. The resource amounts come
from that landing, so a proposed catalog change cannot reprice past usage. An empty list
means no recorded landings in this complete base snapshot. A duplicate identity is invalid.

Compare the combined candidate to this base, in the same submission order as the proposal
preview. A proposed replacement contributes only its difference from the landed amount.
A standard request that fits reserves provisionally for subsequent requests in that candidate.
A denied connection blocks the request even if another connection needs review. A request
awaiting review consumes nothing. An otherwise permissible request that exceeds a limit is
blocked and makes no reservation. For each pool and dimension, report the largest positive
shortfall of a blocked candidate request. The landed ledger changes only on receipt of a
new base revision. Requested prices and proposed inventory remain previews.

Run `python -m pytest -q examples/platform/test_tenant_proposal_resources.py`. The independent
ledger checks two individually admissible changes that compete for the last resources. Their
joint shortfall must carry the base landing, incoming requests, resource quantities and limits
in the ordinary checker's proof.
