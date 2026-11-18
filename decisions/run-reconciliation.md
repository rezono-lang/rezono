# Run reconciliation

The Run invoice drift example owns the reader question `run-reconciliation`. It shows, per profile and run, the predicted order and duration, the measured run, the order registry's account of the selected plans and hourly rates, and the rated and billed totals against their approved ceilings. Use the existing invoice line comparison and its stable plan, item and currency bindings for billing evidence.

A report sourced solely from the registry would describe what was ordered. Independent plan and run evidence makes it possible to check what was expected and what actually ran.

## Independent inputs

| Side | Origin, identity and purpose |
| --- | --- |
| Prediction | An approved run plan identifies the profile, order intent and planned phases. Independently sourced supplier quote and rate evidence gives price validity and terms. The rules derive the forecast order, duration and cost for the plan's intended time. The plan digest identifies this prediction. |
| Measured run | A recorded run supplies run and phase timestamps, and separate activity intervals for each identified resource. The observations carry source references and coverage. Rules derive elapsed time from the run boundaries and each resource's billable usage from its own intervals and the applicable terms. |
| Order registry | A separately captured registry snapshot supplies external order and line records, including selected plans, quantities, currency and hourly rates. Its digest, capture time and coverage identify the reference used to compare with the prediction and the measured deployment. |
| Billed charges | A separately captured invoice supplies each observed `InvoiceLine.minor`, its currency and line identifier. Its source and coverage identify the actual billed amounts. The verified plan and line binding establishes which charges belong to the run. |
| Spending ceiling | A separately approved `std-decision` names the cap, the rated or billed amount it limits, currency, authority, decision date, validity and plan or run scope. Supplier terms, fees or rounding policies that the run adopts also have dated decisions and their supplier sources. |

The plan and run describe the work to be done and what occurred. The registry is external comparison evidence and retains its separate source identity. Join on a verified run, plan and order identity and on stable line and currency keys. Where evidence uses alternate identifiers, use `std-identity` with the originating equivalence statements. Use `std-time` for phase boundaries and for which quote or observed terms apply. Apply the ceiling through `std-decision`.

## Derivation and publication

Compare planned duration and deployment with the measured run. Compare the forecast's selected plans, quantities and rates with the separately captured order registry. Compare measured deployment identity with the registry where both sources identify the same scope. A drift finding cites independently originated evidence for each side of its comparison.

Calculate each resource's usage charge from its measured billable quantity and independently recorded registry rate. Include supported fees under the applicable terms and sum exact amounts for the profile. Keep the resulting rated total and the invoice's billed total as separately identified amounts. Compare them where both sides cover the same scope. A cap comparison uses the amount specified by the applicable decision and names that basis in the finding. An overrun requires that amount to exceed the separately approved cap.

A rated-total witness cites the resource intervals, registered rates and applicable charge terms. A billed-total witness cites the independently matched invoice lines. A cap comparison also cites the applicable ceiling decision. Missing per-resource usage leaves the affected rated total unknown even when the run's elapsed time is known. Missing invoice coverage leaves the billed total and its cap comparison unknown even when the rated total is known. A duplicate or ambiguous line binding, missing scope coverage, unknown time or incomparable currency leaves the affected result unresolved. When full evidence certifies that only one side has an item, publish the one-sided comparison with its coverage proof.

Publish the per-profile reconciliation, detailed differences and explicit unresolved status. The reader question in `questions.yaml` links them to `grounds` from `std-explain`. Its witnesses keep the plan, run and registry source leaves distinguishable. A role can receive a comparison through a witness whose required grounds it can read. Text and headings come from the message catalogue. Adapters read the replay and reference data. Rules and the exact calculation layer derive the differences and costs.

## Independent acceptance evidence

Freeze an independently authored plan, run recording and order registry. The plan predicts two hours of elapsed time and two instances of plan A with two billable hours each at 45 minor units per hour, for a forecast of 180. The recorded run spans 00:00 to 03:00 UTC. Separate observations record resource `a1` active from 00:00 to 03:00 and resource `b1` active from 00:00 to 03:00. The order registry binds `a1` to plan A at 50 and `b1` to plan B at 65 minor units per hour. The fixture terms bill those active intervals and specify zero additional fees. The rated charges are 150 and 195. A separate decision sets a ceiling of 300 on rated usage, so the total of 345 exceeds it by 45. The elapsed-time comparison is 7,200 planned seconds against 10,800 measured seconds. The rate comparison shows 45 versus 50 for A with different source leaves. A separately authored invoice can establish the billed total where the two lines match the run.

In a counterexample, move the stop for `b1` to 01:00 and keep the same 00:00 to 03:00 run span, `a1` interval, registry and cap. The first resource still contributes 150 and the second contributes 65. The rated total is 215 and stays within the cap. In a separate case, remove the stop observation for `b1`. The elapsed run time stays known and the rated total is unknown. An invoice can still establish billed charges for that scope, while the resource interval remains unknown.

For the original three-hour resource intervals, freeze a separate complete invoice with observed `InvoiceLine.minor` values of 135 for `a1` and 195 for `b1`, corresponding to billed hourly rates of 45 and 65. The registry still gives hourly rates of 50 and 65. The rated total is 345 and the billed total is 330, with independent evidence for both. With separately approved ceilings of 340 for each basis, the rated overrun is 5 and the billed overrun is 0. Removing the invoice leaves billed spending and its cap comparison unknown. The rated total and rated cap comparison remain supported.

Include a matched replay and remove one evidence source at a time. A missing registry removes support for the rated total and the registered rate comparison while leaving the independently measured run duration intact. Change only the measured resource usage and only the registry rate in separate cases. The first preserves the recorded rates, and the second preserves the measured duration. Without a valid cap, the applicable amount can still be known while its cap comparison remains unresolved.

Give `run/tests/test_run_reconciliation.py` its own acceptance case. Read the published comparisons and witnesses and verify that each comparison identifies both sources. The handwritten fixture and separate exact arithmetic are the oracle. The captured order registry remains a reference source, including when it differs from the forecast.
