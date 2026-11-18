# Tenant delivery inventory in the request preview

Use the platform pack's public request preview to answer what each submitted file would deliver. A delivery is identified by its tenant and a one-based integer within that tenant. Order by submission time and break ties by service name. The pair represents the same delivery as the catalog's display key (for example, `elm` and `2` identify `elm-2`). Keeping the integer in the pack lets rules use it directly. Retaining the service in the number relation ties every result back to its request file.

| Derived relation | Columns in order |
| --- | --- |
| `tenant_delivery_number` | tenant, service, number |
| `tenant_delivery_item` | tenant, number, catalog component, requested item, requested size |
| `tenant_delivery_placement` | tenant, number, provision, catalog component |
| `tenant_delivery_scope` | tenant, artifact, scope owner |
| `tenant_apply_target` | GitOps project owner, destination cluster owner, destination delivery number |

Join request items to catalog components and provisions. Project each tenant-scoped binding once per requesting tenant, even when multiple services use its identity organization, secret policy, registry project or GitOps project. The secret scope owner identifies the tenant's vault namespace. A GitOps project's targets identify its own delivery clusters. Keep both owners in each target row so an unintended grant to another tenant's cluster is observable.

The number module can start from the request tables already present. The item and placement module reuses the trusted catalog input for components and provisions. The scope and target module adds the catalog's binding declarations as typed inputs once that shared adapter work lands. The adapter converts source declarations. Rules derive order, inventory and targets. These relations describe proposed inventory. Read grants, reviewer decisions, costs and observed reconciliation status have their own acceptance cases.

For the independent expectation, run the standalone tenant calculation on the exact request files passed to the preview. Compare complete sorted relations after inserting a second service in the same tenant, changing a catalog binding, and withdrawing a tenant's request. A service's delivery number, its requested components, its project owner and its target must stay associated throughout.
