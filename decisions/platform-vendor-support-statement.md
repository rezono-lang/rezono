# Vendor support statement per product series

The reference platform answers which support ends soon from the maker's own support statement for a product series. This follows the form of [vendor transport evidence](platform-vendor-transport-evidence.md) and of the release comparison in `rules/keycloak_release.dl`.

## What is recorded

One fact file holds the pinned statement: `facts/kubernetes_support_source.yaml` with one `series_support_source` row per product series. It carries the product, series, latest patch, support end, the page URL and the SHA-256 of the page bytes. The rule `published_series_support` publishes the statement when the product is registered and the statement exists. Product identifiers are fact values, so the rule names no product.

The statement's sidecar names the maker's publication: each source carries the record's page URL. It does not point to a file under `acceptance/`. Those files are the expectations of the tests, and a fact that cites them proves only that the test and the fact agree.

`facts/kubernetes_support.yaml` registers the product and holds a separately authored register row, `series_support_reference`, with product, series and the support end the platform plans with. Its source is the pack file itself. The register never publishes support. When its support end differs from the statement for the same product and series, the rule derives `series_support_end_drift(reference, source, product, series, expected, observed)`, with the register date as expected and the statement date as observed. A missing register row gives no drift and leaves the published support as it is.

## Why not two agreeing rows

Earlier the pack held `series_support_evidence` and `series_support_source` with the same values from the same page, and the rule published only when both agreed. Both rows came from one reading of one page in one change, so their agreement suggested a confirmation that was not there. The evidence row is gone. A second row returns only as a real comparison: the register is written for planning, can disagree with the maker, and the disagreement is a finding.

## Considered

Keeping the two rows and pointing the second at a different page would need a second publisher statement that does not exist for a Kubernetes series. A register row with drift claims no more than the evidence holds and gives the platform owner a finding when the plan and the maker diverge.
