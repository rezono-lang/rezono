# Publish platform comparison rows with source keys

Provide a tabular comparison for placement versus the CMDB export and for network policy versus recorded observations. Publish equal, different or not comparable by topic and canonical key. Include the existing source keys and a proof for each row.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Platform placement and policy | Existing platform design, provider and policy decisions supply the inputs. Derive placements and the exact effective policy snapshot using the platform rules and `std-decision`. |
| CMDB placement reference | Reuse the scoped export, observations and coverage in the [CMDB reference rules](../examples/platform/rules/cmdb_reference.dl). These records preserve what the independent system reported and where it reported it. They do not establish a platform placement. |
| Network observations and coverage | An identified network collector measures verdicts at their source event times. Reuse the `std-loop` flow evidence, snapshot binding and [complete sweep](../packs/std-loop/rules/complete_sweep.dl). Preserve event and receipt keys, run, collector, window and source positions. These observations are independent of the expected state, including when the expected state schedules a probe. |

Reuse existing domain facts, typed observations and reference inputs. No stored report fact or cache is needed. Introduce a binding only if it states an independently known relationship such as a deployment revision for a collection window, with an identified source. Keep that public contract independent of a collector or exporter's table layout. Its role is to make the two comparison scopes commensurate.

## Rules and proof

Join placement by canonical service identity using `std-identity` when a mapping is needed, and compare the known placement sets within the export scope. For flows, join the source, destination, protocol and port within the exact run, collector, window and uniquely bound policy snapshot. Reuse `std-loop` scoping and `std-time` cut semantics. Any policy-based comparison threshold or precedence belongs to a dated `std-decision` record with decider. Use the existing drift rules to keep their findings visible alongside the comparison.

Both sides must have a comparable key and known value for equal or different. A one-sided key produces not comparable with its existing source key and the applicable unmatched or uncovered reason. A conflicted value, missing or ambiguous snapshot, or incomplete required scope also produces not comparable with specific evidence. Keep a coverage witness when claiming a departure was not observed. A missing event does not create an opposing value. An observation outside the policy's keyed terms can still support a drift finding without becoming a matched comparison.

Each published comparison uses the source revision and row keys for all available grounds, and the applicable identity, scope and coverage grounds. `std-access` withholds a conclusion if its role cannot read its entire witness. Channel labels and reader text come from pack tables and message catalogs. This decision supplies rows and proofs for later views.

## Acceptance

The reader question `comparison-report` and `test_comparison_publication.py::test_comparison_publication` read exact rows and witnesses from the publication. Author separate placement and reference inputs for equality, a mismatched placement set, a reference-only service, a desired-only service and an out-of-scope service. Author separate expected policy and recorded verdicts for matched equal and different, both one-sided cases, an incomplete sweep, ambiguous snapshots and conflicting verdicts. Keep the independently written expected rows separate from those reference and observation inputs. Use the existing recorded flow fixtures for the offline calculation. A claim based on the live network uses the actual run's recorder evidence.

A chart or a source-by-source join on display names can obscure unmatched rows and coverage. The typed comparison gives a verifier enough information to reproduce each reported relationship before any visual presentation is added.
