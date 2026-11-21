---
decider: [core]
decided_on: 2026-11-18
valid_from: 2026-11-18
state: in_force
subject: live-feldera-ci
---

# Run the live Feldera oracle after merge

Run a dedicated GitHub Actions workflow, .github/workflows/feldera-oracle.yml, every night on main (cron `17 2 * * *`, UTC) and by manual dispatch. It does not run on a push to main. Keep the existing required pull-request check within its time budget. Use an ephemeral service on the standard GitHub-hosted Linux runner. Give the job read-only repository access. It requires no repository secrets, paid service, persistent deployment or external credentials.

The CI builder owns .github/workflows/feldera-oracle.yml and its entry point, bash compiler/ci/run_feldera_oracle.sh. The workflow runs on ubuntu in four jobs, each with its own timeout: `seed` compiles the stock Feldera dependencies once (20 minutes), `compare` runs nine shards in parallel (120 minutes each), `oracle` merges the shard reports and verifies them (10 minutes), and `report` records a confirmed disagreement of a scheduled run on main as an issue (15 minutes). One run at a time per ref, without cancelling a running one.

Why nightly and not on every push to main: one run compiles thousands of generated operator crates and can take up to an hour, so a run per merge would queue behind the next merge and report on a revision that is already gone. A nightly run on main compares the whole tree once a day, and its report names the first disagreement and the last green revision of main. A change to Feldera SQL generation or to the live comparison does not wait for the night: the workflow is dispatched on the pull request's branch, and the required evidence review (scripts/feldera_admission.py) accepts the pull request only with a successful dispatch for its exact head revision. When that review blocks the head of a branch in this repository, Resume Feldera evidence review dispatches the workflow on the branch itself, unless a dispatched run for that revision is already queued, running or passed; its per-revision concurrency group keeps two blocked reviews of one head from dispatching twice. A pull request from a fork gets no dispatch.

Start the Feldera image pinned by digest in compiler/ci/run_feldera_oracle.sh. Verify that this image supports the HTTP pipeline API and Rust UDF compilation used by compiler/tests/feldera.py. Bind the service to loopback, bound the readiness wait and the job time, and remove the service and its local data on every exit. Use the repository's locked Python dependencies, generated contract types and the existing Souffle bootstrap for example collection.

Run the existing live compiler tests for calculations, bounds and rule properties; the example SQL and incremental-rule suites; and the platform delta/proof test. Use exactly the same node selection and repository root for collection and execution. Record the collected node IDs, one per line, before running them. Reject an empty compiler or example selection, an absent platform delta test, a missing endpoint and collection errors. Set FELDERA_URL before collection. Pass the recording and the resulting pytest JUnit XML to the verifier below. Retain the test report on failure. Do not retry broken comparisons as successful empty runs.

The compiler owns compiler/ci/verify_feldera_run.py. Its positional arguments are the collected-node file and the XML report. Require the exact collected cases to appear once and pass, including parameter cases. The platform live test and at least one live compiler case must be present. Pytest can exit successfully when all selected cases skipped. Any skipped, failed, errored, missing, duplicated or unexpected case must produce a nonzero exit. Missing or malformed inputs also fail. The worker implementing this verifier can use the standard library alone.

The separate workflow task depends on the verifier and the platform delta test being on main. GitHub enables dispatch from the default branch. Merge the reviewed workflow, then verify its first scheduled run or a manual dispatch on main. The first successful run must include actual passing compiler and example comparisons and the platform proof comparison in its report. A workflow definition or a skipped run cannot establish engine parity.
