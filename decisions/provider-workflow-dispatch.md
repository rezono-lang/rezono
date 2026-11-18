# Provider workflow dispatch boundary

Use `.github/workflows/provider-run.yml` for the operator's provider run.
Its only event is `workflow_dispatch`. A small job named `verify_ref` checks
the full runner-provided ref with `test "$GITHUB_REF" = refs/heads/main` under
`sh` or `bash`. This shell comparison is case-sensitive. The job only checks
the ref and has no provider operation.

Place every other job in the literal `provider-run` environment behind that
check. Normal jobs can depend on it directly or through preparation jobs.
GitHub's default success condition then propagates a failed or skipped check.
A cleanup job that runs after a failure lists `verify_ref` as a direct
dependency and checks its success explicitly in its job condition. Inside
an admitted job, steps may use normal failure cleanup. The operator configures
the environment's required reviewer and its main-branch deployment restriction.

## Separate acceptance for provider wiring

The offline structural test proves the trigger, static environment and a
reachable job named `provider_run`. Synthetic jobs exercise its success and
cleanup paths. Their commands do not establish any provider operation.

An open integration task remains before the workflow can meet the run
acceptance criterion. The [provider port decision](run-provider-ports.md)
defines operations and the shared executor; it does not yet name a live
command. Once that command exists, check that the actual workflow invokes
it and exercise that same entry point with recording ports. Require the
approved plan's single order through the shared executor, delivery and a
complete cleanup inventory. Replacing the invocation with a no-op must fail
that test. The [operator guide](../run/OPERATOR.md) also requires a durable
claim and separately verified deployment protection before live use.
