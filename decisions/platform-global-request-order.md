# Global order for platform requests

Expose `request_ordinal(request, ordinal)` as an ordinary derived relation in the platform request preview. Its first column is the request's team/service identifier and its second is a one-based whole number. This is the order in which admission can consider requests across tenants. Per-tenant delivery numbers identify deliveries within a tenant and can repeat across tenants.

Rank complete requests by UTC submission instant, then by tenant and service identifier in ascending order. Compare every supplied fractional digit and treat trailing zeros as equivalent. A whole second precedes a positive fraction of that second. Input enumeration and file creation order have no effect. Use all requests that have a request identity, submission instant, tenant and service. A missing ordering ground excludes that request, and it does not consume a position. Receipts, approvals, available capacity and admission results do not establish an ordering ground.

The pack can compare typed whole-number keys from the adapter for individual ordering fields. Derive the final ordinal from the complete requests in the pack. The input set determines the number of positions. For the admission policy see [the tenant request decision](platform-tenants.md) and [the withdrawal scenario](platform-admission-assumption.md).
