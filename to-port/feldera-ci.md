Target-folder: compiler

Run the Feldera oracle in CI from a pinned service image. Provision an isolated endpoint, wait for readiness and set FELDERA_URL for the compiler and example suites. Tear down the service after each run. Acceptance requires both suites to execute their Feldera comparisons and the CI skip report to contain no missing-endpoint skips.
