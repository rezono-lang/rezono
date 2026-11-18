# Explain network policy from its governing decisions

Publish the decisions governing a flow, their standing on the reference date, their deciders and proposals that could affect the flow. Compare effective policy with a separately recorded zone matrix or traffic table.

## Inputs and origins

| Input | Origin and reason to keep it |
| --- | --- |
| Declared flow and protection scope | Independent platform design choices establish intent, endpoints, transport and demand or offer. Reuse the [cluster flow rules](../examples/platform/rules/cluster_flow.dl) and [firewall witnesses](../examples/platform/rules/firewall_witness.dl) where their scopes match. |
| Policy decision and its applicability | `std-decision` records the decider, decision date and validity. A typed binding may state that a decision governs an exact directed endpoint, protocol and port tuple, with function or boundary where required. Declare the binding only when the decision's scope is independently authored and cannot be derived from existing bindings. It supplies the governance scope needed by the question. |
| Applied-policy observation | A controller or enforcement readback can report a specific applied revision and scope. A current application claim needs this separate observation as well as the effective decision. |
| Recorded matrix or traffic table | Read it as a versioned reference source with its own row positions, including declared coverage when available. It has no authority over policy, desired routing or the status of a decision. |

An applicability binding describes the subject of a decision, independent of an exporter layout. A readback describes an observation of an enforcement point. Effective standing, applied agreement and drift are derived rows.

## Rules and proof

Join the flow to each binding on the full typed key and referent identities. Use `std-decision` for standing, replacement, proposals and deciders, and `std-time` for the supplied date. Use `std-identity` where endpoints require a canonical mapping. Publish independently applicable decision grounds. Preserve proposal, expired or replaced standing and missing or contradictory evidence as distinguishable outcomes. Missing actor, scope or application evidence leaves the corresponding claim unknown. Record any date window, priority or exception as a decision with its decider and date.

Compare effective policy and its independent reference at the compatible scope and cut. Preserve both source keys and witnesses. A differing stored entry yields drift and leaves current policy unchanged. A partially captured matrix can establish a recorded entry, while a claim that an entry was absent requires a complete scope receipt. Decision standing alone cannot establish that an implementation applied the rule.

## Acceptance

The reader question `network-policy-origins` and `test_network_policy_provenance.py::test_network_policy_provenance` use hand-authored flows with different transport and endpoints, including flows on the same port. A witnessed current decision supports only its own flow. Expiration, a proposal, missing decider and an unrelated application revision each produce the corresponding limited or unknown claim. A changed matrix row produces drift with both source references and leaves the governing decision result unchanged. Verify exact published rows and readable proof, including the recorded actor, validity date and any independently observed revision.

Inferring authorization from a permitted connection or from the displayed matrix conflates intent, execution and reference. Keeping each source distinct also makes a stale or unapproved result explainable to a reader. The expected answer is authored in the test independently of both policy and reference inputs.
