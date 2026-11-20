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
- At least one test function that pytest collects turns from red to green through that lift.
- Every other path is a new evidence file: added, not changed, so that no expectation the
  test already holds can be weakened. It is a regular file (Git mode 100644, no symbolic
  link, not executable), in a directory named `expected/`, `snapshots/` or `vectors/`,
  with a data suffix (`.json`, `.yaml`, `.csv` and the like), such as
  `examples/*/expected/calc/*.json`.
- That directory sits directly in a pack root (a directory with `pack.yaml` at the head),
  in a `tests/` or `test/` directory, or in a directory on the path of the test file. The
  compiler reads a pack's `schema/`, `rezono/`, `facts/`, `labels/`, `messages/`, `rules/`,
  `calc/` and `icons/` as its definition (`DEFINITION` in
  `compiler/rezono_compiler/modules.py`), `schema/` and `rezono/` at any depth. An
  `expected/` inside one of them would change the pack, so no path below such a directory
  counts, and nothing under `packs/` does.
- Nothing else counts as evidence, even inside those directories: no fixture, no
  `*.schema.json`, no `pack.yaml`, no `not-yet.json`, nothing under `blocked/`,
  `contracts/` or `.github/`. These configure what runs or what is accepted.
- Nothing else changes: no source, no other test file, no other mark, no test helper or
  `conftest.py`, no workflow, no changed or removed file.
- The evidence comes from a source independent of the engine: worked by hand, computed
  by an oracle or another implementation, or taken from a published reference, never
  written from the engine's own output. The pull request says how it was made.
- A reviewer has read that source before it lands: the pull request carries the read label
  `p1-read-<full head commit id>` of `decisions/checker-and-access-review.md`, as a change to
  the checker does. The guard cannot see where evidence came from, and a pull request lands
  once its checks are green, so without the label a planner could record the engine's
  output as the expectation and lift the mark: the test would then compare the engine with
  itself. The guard requires the label for every `COMPLETED` pull request, and a new push
  needs a new label.

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
   the head. Every selected case must then pass: none may fail, skip or xfail, and at
   least one must run. A skipped case would say nothing about the evidence.

Both scripts run from the base revision, so the exception applies to pull requests after
the one that introduces it lands.

## Alternatives

- **Two pull requests, as before.** The evidence lands first, the lift later. Neither shows
  that the evidence turns the test green, and the second needs no planner at all.
- **Let the label allow any lift beside protected changes.** That is the gap the rule
  closes: a planner could weaken an expectation and lift the mark in one step.
- **Rely on the base alone.** The base shows that the test is red without the new data
  and green with it, but not that the data is right: data written from the engine's own
  output passes as well. So a reviewer reads the source too.
- **A provenance line in the pull request that the guard reads.** Anyone can write the
  line; only a reader can tell whether it is true.

## Not covered

- A test whose every case carries the `cluster` mark is not run on an ordinary runner.
  `run` accepts that, as for any added cluster test, and `green` then fails because
  nothing passed. Such a completion needs two pull requests, as before.
- A lifted mark on one `pytest.param` counts only when the parameters sit in the
  `parametrize` decorator and no other case of that test keeps a red mark: only then does
  the test function turn green. The whole function is selected, so its other cases run
  too and must pass with the new evidence.
