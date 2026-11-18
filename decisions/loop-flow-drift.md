# Compare declared service flows with a recorded Hubble sweep

A policy snapshot identifies a closed set of allowed service tuples. Bind the snapshot to a run, collector and window before comparing any rows. For a tuple outside that set, the policy-side witness is the snapshot ID together with the four columns used for the negative lookup. A missing snapshot binding leaves the comparison out of scope. Hubble supplies event IDs, verdicts and coverage. Only a policy row can supply an allowance.

Use the typed input columns in `loop/tests/flow_drift_cases.py`. Window bounds are integer source-event ticks, start inclusive and end exclusive. Each sweep has a stable reference and a nonempty inventory of expected nodes pinned for that window. A node's final report gives its actual coverage bounds, the count of interior gaps and the lost-event count. Reports are final per node and scope. The `complete_sweep` relation returns (run, collector, window, sweep reference) only if every expected node covered the whole window without gaps or lost events. Receipts from other collectors, runs, windows or nodes cannot fill a hole.

The `flow_drift` relation returns the scope, source, destination, protocol, destination port, class, status, policy-side witness and reference-side witness. Keep one row per distinct pair of witnesses. Compare observed events inside the same scope and time interval even on a partial sweep. For each allowed tuple with no such event, require the matching complete sweep.

| Class | Policy | Hubble | Status | Witness pair |
| --- | --- | --- | --- | --- |
| matched | Allowed | Forwarded | valid | Allowance row and flow event |
| unseen | Allowed | No event in complete sweep | unknown | Allowance row and completed sweep |
| blocked | Allowed | Dropped | violated | Allowance row and flow event |
| prevented | No allowance | Dropped | absent | Closed policy snapshot and flow event |
| excess | No allowance | Forwarded | violated | Closed policy snapshot and flow event |

The statuses belong to `contracts/view.yaml`. Blocked and excess rows are findings a reader can inspect. The existing generic object-drift rule interprets explicit evidence that an expected object is absent. Applying that rule to idle allowed flows would confuse lack of traffic with a violation. Keep the flow comparison in std-loop rules and preserve the recorded observation rows and their identities when substituting a different policy snapshot.

The acceptance fixture reuses the declared synthetic cases in `loop/tests/fixtures/network.json`. Its events and coverage reports are handwritten data. A disposable-cluster recording would be separate evidence that the collector and policy enforcement actually produced such rows.
