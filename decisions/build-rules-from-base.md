# Take the test plan and the test count from the base

The required `check` decides what a candidate must run and verifies that every inventoried test started and finished exactly once. Both decisions now come from the base revision: `pull_request.base.sha` in a pull request, `merge_group.base_sha` in the merge queue, and the commit itself on a push to `main`. The candidate still executes its own shards. [CI workflow](../.github/workflows/ci.yml) · [Current selector](../scripts/components.py) · [Build reconciliation](build-reconciliation.md)

## Choice

- `discover` extracts the base `scripts/` into the hidden directory `.build-base/` of the candidate checkout, from the history it already fetched. `ci-matrix` and `inventory` run from that copy. Because the script takes the parent of its own directory as the repository, the base rules read the candidate's tree.
- The inventory step unsets `PYTEST_ADDOPTS` and `PYTEST_PLUGINS`, so the candidate's environment action cannot narrow the collection.
- `check` checks out only `scripts/` of the base and runs `verify-execution` from it. This replaces a full checkout of the candidate, so the job does not get heavier.
- `run-shard` and `execute-worker` stay on the candidate. They are what is being executed, and the base count verifies them.

## A pull request that changes `scripts/components.py`

Its own regressions in `.github/workflows/tests/test_components.py` import the candidate copy and run in `discover`, and its `run-shard` executes the shards. The base selects which suites run and counts them; changing `scripts/components.py` selects every suite. A new selection rule therefore takes effect for the pull requests after it lands. A change to the matrix outputs or to the inventory file that the candidate's `run-shard` reads must stay readable by the base copy, or land in two steps: first the reader, then the writer.

## Alternatives

- **Pin the rules to a commit in the workflow.** Every rule change would also need a workflow change, and the pin would drift from `main`.
- **Overwrite the candidate's `scripts/components.py` with the base copy.** The candidate's regressions would then test the base copy.
- **Run `run-shard` from the base as well.** A candidate's executor change would then first run on `main`. The base count already detects a shard that leaves out a test.

## Remaining gaps

- `addopts` in a candidate `pyproject.toml` applies to both the inventory and the run. `--deselect`, `-k` and `-m` are rejected by the base inventory, but `--ignore` and `--ignore-glob` drop a file from both silently. A base step that requires every test file to yield at least one item, or a blocked-file record, would close this.
- `conftest.py` hooks and `collect_ignore` can drop items in the same way. These files are protected test paths, so the test-evidence guard reports a change to them.
- The candidate's environment action installs the interpreter and the packages that collect and run the tests. It can add a pytest plugin through an entry point, or change `PATH`. Taking the action from the base would close this, at the cost of testing an action change only after it lands.
- The candidate's `execute-worker` writes the start and finish journals that the base counts, so a candidate can forge them. Any evidence produced inside the test process shares this limit.
