# Contributing

This guide says only what holds at the commit you read it from.

## Report a bug or a vulnerability

- Report a bug by opening an issue. Attach the smallest pack that shows it, the command you ran and what you expected.
- Report a vulnerability as [SECURITY.md](SECURITY.md) says, not in a public issue.

## Licence

A contribution falls under the licence of the path it touches, as [NOTICE](NOTICE) says.

## Pull requests

- If you are not one of the project's own agents, work from a fork of the repository. Do not claim a task by pushing a branch to this repository; open a pull request from your fork.
- Commit under your own name. The commit identity in [WORKER.md](WORKER.md) is for the project's own agents.
- Checks that run code from a pull request by an outside contributor start only after the maintainer approves them.
- Only the maintainer sets the label `planner`.

## How a pull request lands

- Read [AGENTS.md](AGENTS.md) and the working instructions of the component you change. The project's own agents select one expected failure from `python scripts/red_list.py` and follow [the worker card](WORKER.md).
- A pull request needs the checks `check`, `Light checks` and `Inspect test evidence`. A read-only workflow from the base revision checks the proposed Git objects and attaches its result to the reviewed commit.
- Moving or editing tests, fixtures, recorded outcomes, test helpers, a `pytest.toml`, `.pytest.toml` or `.pytest.ini`, the pytest section of a `pyproject.toml`, `setup.cfg` or `tox.ini`, or the policy itself, or marking a green test red, including the workflows that define the required checks (`.github/workflows/ci.yml`, `.github/workflows/disposable-cluster.yml` and `.github/workflows/red-policy.yml`), needs the label `planner` and a reason in the pull request. The label does not switch the review off: a pull request that lifts a red mark changes no other protected path, except that a planner may lift one mark beside only new evidence data its test reads, added under `expected/`, `snapshots/` or `vectors/` in a pack root or test directory ([evidence completion](decisions/evidence-completion.md)), or re-pin the imports of a fixture pack to the hash the guard computes ([fixture pin update](decisions/fixture-pin-update.md)), and every new or changed red mark sets `strict=True` without `run=False`.
- The review lists removed protected files and test functions, and changed evidence, as `REMOVED` and `CHANGED` lines in its log and job summary. These lines do not block.
- Pull requests land through the merge queue. There `Inspect test evidence` reviews the queued change again against the commit it lands on, with the policy from that commit and the pull request's current label, so a pull request reviewed against an older base cannot land under an older policy. The queue runs every discovered component against the combined changes.
- The compiler and example suites require the pinned Soufflé 2.5 oracle in CI. Job summaries report actual skips by reason, including Feldera comparisons that need an endpoint; `python scripts/red_list.py --skips report.xml` reproduces a summary from a pytest JUnit report.
- Inactive task claims without an open pull request expire after four hours.
