# Explain platform support severity and version policy

Publish the chosen version with its deciding record, the newest cycle the publisher still supports on the stated date, and the derived severity beside the independently recorded severity.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Chosen release and version policy | Platform design selects a product. A pin, governed preference, support threshold or evaluation horizon points to a `std-decision` record naming the decider, decision date and validity. A typed policy binding is warranted when the decision supplies an explicit parameter unavailable in the current facts. It represents the support policy used to assess the selected version. |
| Vendor support interval and cycle | The vendor's release and support publication supplies cycle identity, first supported date and support end where known. Keep URL, revision or digest and position. Reuse [`SeriesSupportSource`](../examples/platform/schema/kubernetes_support.yaml) and vendor support statements. Add a typed first-day or scope statement only when the publisher actually provides it and the existing evidence cannot represent it. It is required to establish ordering or the candidate set. |
| Registered assessment | An independent dated assessment register supplies the recorded severity, exact release or cycle key and revision. It is comparison evidence. |

Keep any extra facts in domain terms, with an identifiable decision or vendor statement as origin. Derived severity, the set of latest supported cycles and agreement with the register have no stored input rows.

## Rules and proof

Derive the chosen release from the platform's provider and pin rules, and cite the valid decision behind the selection. Project version-to-cycle identity from evidenced mappings. Use `std-time` to evaluate vendor support at the reference date and `std-order` to compare the evidenced start dates of supported candidates. A cycle with a later first day may have a lexically smaller label. Preserve both candidates when different cycles share the latest known start day. A single claim of the newest cycle needs evidence that the relevant publisher inventory is complete or otherwise bounds later candidates.

Derive severity from the chosen cycle's verified dates and the applicable `std-decision` threshold records. Use the published support window's stated calendar boundary and test the severity policy's own threshold separately. Contradictory statements about one cycle, an unmapped pin, missing publisher coverage and an absent applicable policy remain specific unknowns. Include the pin, policy, date, vendor scope, selected cycle and the candidate grounds used by the order in the witness.

Compare derived severity with the independent register on the matching product, cycle, scope and date. A changed register can change drift only. A changed, effective policy decision can change computed severity. Publish unknown with the missing or disputed ground when a required key or value is unavailable.

## Acceptance

The reader question `version-support` and `test_support_version_policy.py::test_support_version_policy` use a small independent fixture with a dated pin and policy, supported cycles ordered differently from their version labels, an equal-start pair and a newer unsupported release. Check the threshold boundary from the authored decision, a proposed replacement and an absent or conflicting vendor statement. Change just the registered severity and require changed drift with unchanged derived severity and distinct source keys. Verify the published rows and witnesses available to the reader. Use the pinned public support statement for the real product evidence and keep synthetic cases separate.

Release recency cannot supply support dates. A recorded severity cannot decide the computed severity. Explicit vendor intervals and dated policy give independent grounds for each result and for the comparison.
