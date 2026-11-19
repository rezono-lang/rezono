# A planner may complete the evidence of one red test

`scripts/red_guard.py` refuses a pull request that lifts a red mark while any other
protected path changes: "Lift marks in a pull request of their own". The rule keeps a
lifted mark from hiding a weakened expectation. The planner label does not switch it off.

Some red tests wait for evidence data, not for source. A test that compares output with
recorded files fails until those files exist. The planner who writes the files from an
independent source is the one who can show that the test then passes. Under the rule
above, that took two pull requests, and the first one could not show anything: the files
landed while the test stayed red, and a worker lifted the mark later without new evidence.

## Decision

With the `planner` label, a pull request may lift one red mark beside the evidence data
that its test reads. This is an evidence completion. It applies when all of these hold:

- Exactly one red mark goes, in one test file. That file changes only by the lift, and
  every other mark in it stays exactly as it was, reason included.
- At least one test function turns from red to green through that lift.
- Every other changed path is added or changed evidence data: a protected file that is not
  policy (`POLICY` in `red_guard.py`) and whose suffix is a data format, such as
  `examples/*/expected/**/*.json` or `tests/conformance/*.yaml`.
- Nothing else changes: no source, no other test file, no other mark, no test helper or
  `conftest.py`, no workflow, no removed file.

The guard reports such a pull request as `COMPLETED <path>::<test>`. Without the label, or
with anything else in the pull request, the refusal stands.

## Proof on the base

The guard reads only Git objects, so it cannot tell whether the test reads the new data.
`scripts/red_before.py` shows it in the required check "Added tests on the base source":

1. `discover` marks an evidence completion as required, like a mixed pull request.
2. `prepare` checks out the base and lays only the test file over it. The evidence stays
   at the base. The selection holds the tests that turn green.
3. `run` must see at least one of them fail there, with the mark lifted and without the
   new evidence. If they all pass, the evidence was not what made the test red.
4. `green` lays the evidence over the base too. Since nothing else changes, that tree is
   the head. Every selected test must then pass, and at least one must run.

Both scripts run from the base revision, so the exception applies to pull requests after
the one that introduces it lands.

## Alternatives

- **Two pull requests, as before.** The evidence lands first, the lift later. Neither shows
  that the evidence turns the test green, and the second needs no planner at all.
- **Let the label allow any lift beside protected changes.** That is the gap the rule
  closes: a planner could weaken an expectation and lift the mark in one step.
- **Ask a reviewer to read each such pull request.** It adds a person to the path while
  the base already holds what decides the question: the test, red, without the new data.

## Not covered

- A test whose every case carries the `cluster` mark is not run on an ordinary runner.
  `run` accepts that, as for any added cluster test, and `green` then fails because
  nothing passed. Such a completion needs two pull requests, as before.
- A lifted mark on one `pytest.param` counts only when the parameters sit in the
  `parametrize` decorator and no other case of that test keeps a red mark: only then does
  the test function turn green. The whole function is selected, so its other cases run
  too and must pass with the new evidence.
