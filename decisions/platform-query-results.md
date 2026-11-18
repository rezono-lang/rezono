# Query evidence and portal rendering

The reference pack exposes capability and policy evidence as derived relations. Each query module owns its named relation. All source and target identifiers, ports and evidence identifiers come from authored data or its joins. Retain one row per distinct witness, so two valid ports or two offers stay visible.

| Relation | Column order |
| --- | --- |
| choice_evidence | source, target, function, port, choice id, offer id |
| unique_evidence | source, target, function, port, demand id, offer id |
| other_provider | source, available target, function, chosen target, choice id |
| firewall_witness | source zone, target zone, port, source, target, function |
| in_zone_witness | zone, source, target, function, port |
| recovery_flow_delta | change, source, target, function, port |
| recovery_rule_delta | change, source zone, target zone, port |
| support_unknown | service, running release, support state |

For support reporting, absence of vendor evidence makes the support state unknown, including for a release that is current. For recovery comparison, compare requested flows with the effective flows after enforcing isolation. Relaxing the principle restores any excluded flow. Take the set difference after the appropriate projection to avoid claiming that an unchanged firewall rule disappeared. Zone-level evidence explains the overview. The deployable per-flow firewall uses the finer address-based decision.

The portal example has three independent, pure rendering functions. They consume normalized input chosen by the pack or an observed event. The catalog renderer produces the Backstage component in the tenant namespace with its team as owner. The request-file renderer serializes a normalized request at the team/service path in Git. The commit-status renderer takes an already observed pending, success or failure state and event time. It retains the proposal SHA and builds the context from tenant, delivery and step. Each case uses the same form for both tenants. These functions perform no network operations.

A live observation is required for elapsed times and observed-versus-desired findings. A filed request, a rendered component and a synthetic status tuple are insufficient evidence of completed delivery.
