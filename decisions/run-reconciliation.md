# Run reconciliation

The Run invoice drift example owns the reader question `run-reconciliation`. It shows, per profile and run, the predicted order and duration, the measured run, the order registry's account of the selected plans and hourly rates, and the spending against the approved ceiling. Keep the existing invoice line comparison and use its stable plan, item and currency bindings for the billing evidence it already covers.

A report sourced solely from the registry would describe what was ordered. Independent plan and run evidence makes it possible to check what was expected and what actually ran.

## Independent inputs

| Side | Origin, identity and purpose |
| --- | --- |
| Prediction | An approved run plan identifies the profile, order intent and planned phases. Independently sourced supplier quote and rate evidence gives price validity and terms. The rules derive the forecast order, duration and cost for the plan's intended time. The plan digest identifies this prediction. |
| Measured run | A recorded run supplies original phase timestamps, activity and machine observations, with source references and scope completeness. The run and observation identifiers retain replay identity. The rules derive elapsed time and usage from this evidence. |
| Order registry | A separately captured registry snapshot supplies external order and line records, including selected plans, quantities, currency and hourly rates. Its digest, capture time and coverage identify the reference used to compare with the prediction and the measured deployment. |
| Spending ceiling | A separately approved `std-decision` names the cap, currency, authority, decision date, validity and plan or run scope. Supplier terms, fees or rounding policies that the run adopts also have dated decisions and their supplier sources. |

The plan and run describe the work to be done and what occurred. The registry is external comparison evidence and retains its separate source identity. Join on a verified run, plan and order identity and on stable line and currency keys. Where evidence uses alternate identifiers, use `std-identity` with the originating equivalence statements. Use `std-time` for phase boundaries and for which quote or observed terms apply. Apply the ceiling through `std-decision`.

## Derivation and publication

Compare planned duration and deployment with the measured run. Compare the forecast's selected plans, quantities and rates with the separately captured order registry. Compare measured deployment identity with the registry where both sources identify the same scope. A drift finding cites independently originated evidence for each side of its comparison.

Compute actual spending for a profile from measured billable usage and independently recorded registry rates, plus supported fees under the applicable terms. Use exact amounts. Compare the total with the separately approved cap and report an overrun only above that cap. A witness for the spending or an overrun names the usage, rates, charges, applicable terms and, for the overrun, the cap. A duplicate or ambiguous line binding, missing scope coverage, unknown time or incomparable currency leaves the affected result unresolved. When full evidence certifies that only one side has an item, publish the one-sided comparison with its coverage proof.

Publish the per-profile reconciliation, detailed differences and explicit unresolved status. The reader question in `questions.yaml` links them to `grounds` from `std-explain`. Its witnesses keep the plan, run and registry source leaves distinguishable. A role can receive a comparison through a witness whose required grounds it can read. Text and headings come from the message catalogue. Adapters read the replay and reference data. Rules and the exact calculation layer derive the differences and costs.

## Independent acceptance evidence

Freeze three independently authored inputs. The plan predicts two hours and two instances of plan A at 45 minor units per hour, for a forecast of 180. The recorded run measures three hours and observes one A and one B. The independent order registry records A at 50 and B at 65 minor units per hour. Given a separate ceiling decision of 300, the independent arithmetic gives actual spending of 345 and an overrun of 45. The time difference is 7,200 versus 10,800 seconds. The rate comparison shows 45 versus 50 for A with different source leaves. The registry lines and run events are separate even when they agree on the deployed plans.

Include a matched replay, remove one evidence source at a time, and change only the run duration and only the registry rate in separate counterexamples. A missing registry removes support for actual spending and the rate comparison while leaving supported run duration intact. Changing a measured duration does not change the registered rate comparison. Changing a registry rate does not change the measured duration. Without a valid cap, spending can still be supported but an overrun cannot be asserted.

Give `run/tests/test_run_reconciliation.py` its own acceptance case. Read the published comparisons and witnesses and verify that each comparison identifies both sources. The handwritten fixture and separate exact arithmetic are the oracle. The captured order registry remains a reference source, including when it differs from the forecast.
