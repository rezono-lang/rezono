# Direct provider ports for a bounded run

Use narrow, typed ports for price and availability reads, a single order,
order status, tagged-resource inventory, and cleanup. Keep the provider
adapter separate from the rules that choose the offer. Do not ship deployment
credentials with replay data. The existing loop dispatches operations and
owns attempt state; the adapter never starts another reconciliation loop.

OpenTofu offers provider reuse and a reviewed change plan. Its state records
the binding of configured resources to remote objects. That binding is useful
for managing infrastructure, but an independently requested full inventory is
needed to find a tagged resource missing from local state. Prices and stock
also need authoritative, current provider responses. Even when a provider
offers such data sources, their observations must enter the same model. The
extra state and reconciliation path are unnecessary for this bounded use.

Require a complete, independently fetched inventory to confirm cleanup. An
empty local journal, a successful delete response, a partial listing, and an
unavailable provider are insufficient. Distinguish definitive rejection from
a lost response, and resolve the latter by status with the original key. An
adapter without a recoverable correlation key is ineligible for orders.

The phoenixNAP APIs illustrate a product/price read and separate server
listing, ordering and tagging operations. The published SDK models price as a
binary floating-point value. Read the decimal lexeme from the original JSON
and convert it exactly before comparison. These examples motivate the port
separation; provider selection still requires evidence for boot, storage,
virtualization, charging rules and inventory semantics.

- [OpenTofu v1.13.9 state purpose](https://github.com/opentofu/opentofu/blob/c83e7e50daff10ac704cb0811e9ffd0ad2523759/website/docs/language/state/purpose.mdx)
- [OpenTofu provider configuration](https://github.com/opentofu/opentofu/blob/c83e7e50daff10ac704cb0811e9ffd0ad2523759/website/docs/language/providers/configuration.mdx)
- [Provider billing API](https://github.com/phoenixnap/go-sdk-bmc/blob/7c1060e91d834f84035cdc1aa844c75b3d1b5195/billingapi/api/openapi.yaml)
- [Provider physical server API](https://github.com/phoenixnap/go-sdk-bmc/blob/7c1060e91d834f84035cdc1aa844c75b3d1b5195/bmcapi/api/openapi.yaml)
- [SDK price representation](https://github.com/phoenixnap/go-sdk-bmc/blob/7c1060e91d834f84035cdc1aa844c75b3d1b5195/billingapi/docs/PricingPlan.md)
