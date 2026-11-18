# Provider workflow dispatch boundary

The provider entry point is `.github/workflows/provider-run.yml`. Use one
job with the static GitHub environment `provider-run` and a step identified
as `provider_run`. This gives the operator and offline check a stable target
distinct from the read-only preflight and the disposable host trial.

Enable only `workflow_dispatch`. Put the full `github.ref == 'refs/heads/main'`
condition on the job itself. GitHub expression equality ignores case. As its
first step, run `test "$GITHUB_REF" = refs/heads/main` under `sh` to check
the runner-provided full ref case-sensitively. Subsequent steps use normal
success gating. The provider step must be reachable on a successful main
dispatch. This small job needs no job dependency or matrix. A diagnostic
job with the right condition could otherwise conceal an unguarded provider
step in another job.

The synthetic cases exercise those structural checks without running steps.
The operator configures the environment's required reviewer and restricts
deployments to the main branch. A literal environment reference cannot prove
those server settings. Wire the real entry point only after the provider
ports, durable claim and verification gates in the [operator guide](../run/OPERATOR.md)
exist. Workflow shape alone establishes neither live readiness nor an order.
