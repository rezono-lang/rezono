# Tenant proposal inputs and derived evidence

The operator preview uses the same request files as the portal. The three derived results below are production pack relations returned by the public request preview's `relation NAME` command. The pack consumes typed catalog and proposal inputs. Its adapter only converts declared fields to typed records. A proposal cannot grant itself review authority or read access.

In the trusted catalog, `reviewGrants` lists pairs of reviewer and action. `decisionsByReviewer` lists objects containing reviewer, sourceDelivery, target and port. Only a reviewer granted `approve-connection` can authorize that exact direction, target and port. `readableQuotas` contains objects with id, owner, dimension and amount. These represent independently issued tenant-readable quotas. Both new decision tables and the quota table default to empty. Treat the existing catalog's published capacities, resource vectors, zone matrix, profile zones and item provisions as ordinary input facts. Apply the same request conversion to every submitted team/service path. Extend the adapter only once, after the public input adapter is available.

| Production result | Columns |
| --- | --- |
| tenant_resource_capacity | pool, dimension, demand, limit |
| tenant_resource_shortage | pool, dimension, positive shortage |
| tenant_connection_review | team, delivery, target, port, decision, reason |
| tenant_delivery_component_evidence | reader, delivery, part, component, request item ID |
| tenant_quota_evidence | reader, owned request item ID, quota ID, requested cores, quota amount |

Cross-tenant connections need the peer's matching request and an authorized decision in addition to zone policy. Capacity sums requested reservations before provisioning. A tenant-visible delivery component must have a readable request item as its witness. A tenant-visible quota comparison must have a readable grant for both its item and its own quota. Results carrying another tenant's quota or input use are forbidden, even when they support a numerically equivalent result. The operator's complete proposal comparison contains distinct rows for each reader. Ordinary tenant publications enforce the same reader scope. The independent fixtures cover requested capacity, authority and potential disclosure; the portal renders their results.
