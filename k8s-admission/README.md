# Admission in managed namespaces

Declare each managed Namespace with the label `rezono.dev/admission=enabled` in Git. The binding selects that label. Reconcile its namespace-specific publication and verify its release identity alongside the policies before submitting workloads. The fixture in `fixtures/managed-blue.yaml` supplies the namespace used by the policy round trip.

For a disposable cluster acceptance run, install the declared policy, binding and release parameters and wait for the policy type checks to finish. Submit the platform-rendered isolation baseline and both directional allowances with server-side dry-run. All must pass. Then submit a known wider rule in the same namespace. Require an admission denial identifying the rule and release. A successful positive request alone cannot demonstrate that the binding selected this namespace.
