---
decider: [core]
decided_on: 2026-11-19
valid_from: 2026-11-19
state: in_force
subject: front-door
---

# The front door: readme, quickstart, container and contributing

A newcomer should see what Rezono is, try it, and know under which terms. The readme, its quickstart, a container to run the quickstart in, and a contributing guide are the front door. Each says only what is true at the commit it is read from, and a test holds each to that.

## The readme names no release that is not there

Until the first release there is no wheel, image or package to download. Until `CHANGELOG.md` has a section for a released version (a heading `## <version>`), `README.md` says "There is no release yet." and does not use the word "released". It says how to install from a checkout, which the quickstart already does.

The first release adds its section to `CHANGELOG.md`; the same pull request rewrites the readme and the test.

## The quickstart computes

The quickstart is the sequence of `bash` blocks in `README.md`, in order. `scripts/check-quickstart.sh` runs every block in order in one shell, so a later block uses the working directory and the variables of an earlier one. A block in another language, such as `sh`, is not run.

1. **`library`.** Publish the example and select the green proof check from its manifest. This is the smallest publication.
2. **`subsidy`.** Publish the example in the same working directory and print the same two answers shown in `## Example`: the calculated award and calculation steps for `A001` (together with the article and council decision read from the parameter row, using a second `jq`), and the `assessment` row and unknown award for `A003`. `scripts/check-quickstart.sh` compares the printed output byte for byte with the `text` block below this step. The final command in this block remains a `jq -e` invocation mentioning `witness` so the quickstart proves both computation and witnessed proofs. Neither answer carries a hash or a path, so the output is the same on every run.
3. **One assumption and its difference.** Builds on the `subsidy` publication produced by step 2, in that order; added with the local suppose command; see [local suppose](local-suppose.md).

The check that runs the quickstart in CI is the proof with a clean copy: what the readme lets a newcomer do must succeed.

## A container for every other machine

The readme asks for Ubuntu 24.04 on x86-64 with the pinned Python. For any other machine a `Dockerfile` at the root of the repository builds an image in which the same quickstart succeeds.

- Every `FROM` names its image by digest (`@sha256:`), as other pins in the repository do.
- The readme gives the two commands that build and start the image in an `sh` block, which the quickstart check does not run.
- The image is never published. A release, and anything pushed to a registry, stays with the maintainer.
- A CI job builds the image and runs `scripts/check-quickstart.sh` in it, only when the readme, the `Dockerfile` or `requirements/` change.

## The readme in one screen

Someone who opens the repository sees, in the first screen, what Rezono does, what sets it apart, and one example with an answer and its proof. Everything for maintainers lives elsewhere. `README.md` has at most 150 lines and exactly these seven parts, in this order, under these headings:

1. **`# Rezono`.** One sentence of at most 25 words that says in plain words what Rezono does. It says what the repository's About says: *Facts and rules in, answers with proof out. Every conclusion carries a witness an independent checker verifies.*
2. **`## What you get`.** At most five short lines, each naming something that works at this commit.
3. **`## Example`.** Before the first command: a worked calculation from `examples/subsidy` (replacing the earlier requirement of a single rule copied from the pack's rule files). A `yaml` block shows a few facts from `examples/subsidy/facts/*.yaml` (including `A001` and `A003`), and a `text` block shows two answers in plain words and euro amounts, with no hash and no path:
   - **`A001`:** the award (€ 2,694: cost share € 2,544 at the 24% partial rate for income € 31,400 between the € 30,000 threshold for 3 persons and the € 42,000 limit, plus € 150 advice allowance) and the calculation steps it rests on, each step naming its calculation rule, version, evaluation date, definition and parameter; plus the article and council decision of a read parameter (from the parameter row, printed by a second `jq` in step 2).
   - **`A003`:** the derived `assessment` row (`unknown`, reason `income_statement_not_received`) and an unknown calculated award (never zero). Because the example's separate payment ledger did record a payment for `A003`, the wording states explicitly that the *calculated award* is unknown while the income statement is missing, so a reader who later inspects the ledger is not misled.

   One sentence states that the independent checker verified the witness before publication and that an independent computation (`examples/subsidy/reference.py`) produces the same amount. The `text` block appears word for word in the `text` block under step 2 of the quickstart.
4. **`## Try it`.** The quickstart steps, each `bash` block followed by a `text` block with the output it prints, and the two container commands in an `sh` block.
5. **`## Read further`.** Links to the tutorial (`docs/tutorial.md`), the language guide (`rezono/README.md`), the examples (`examples/`) and `docs/vision.md`.
6. **`## Status`.** "There is no release yet.", and what works at this commit.
7. **`## Licences and contributing`.** Two lines: one that links `LICENSE`, `LICENSES/` and `NOTICE`, one that links `CONTRIBUTING.md`.

Sections may have `###` subheadings, such as one per quickstart step; no other `##` heading appears.

## What moves out of the readme

- **Building a standalone compiler wheel** moves to `rezono/README.md`, beside the language it packages. It names no release: until there is one, there is no released wheel to describe.
- **The required checks** (`check`, `Light checks`, `Inspect test evidence`), the `planner` label and the merge queue move to `CONTRIBUTING.md`, which is where a contributor looks for how a pull request lands.
- **The Dependabot policy** moves to `SECURITY.md`. It is about how alerts are handled and by when, which is what a reporter of a vulnerability reads; `CONTRIBUTING.md` stays about how to contribute.

The headings "Compile an authored Rezono pack" and "Dependency updates" no longer appear in `README.md`.

## The shown output is checked

When a `text` block follows a `bash` block with only blank lines between them, `scripts/check-quickstart.sh` compares that `text` block with the standard output of the `bash` block above it, byte for byte. Standard error is not compared.

- The script runs each `bash` block on its own, but all of them in the same shell, so the working directory and the variables still carry from one block to the next.
- A difference fails the check and prints the expected and the actual output of that block.
- A step whose output differs from run to run, such as a manifest hash or a temporary path, gets no `text` block.
- A `bash` block without a `text` block below it is run but not compared.

So the output the readme shows is the output a newcomer gets, and the answer in the example is the answer the engine computes.

## Contributing

`CONTRIBUTING.md` says only what holds now:

- report a bug with an issue and the smallest pack that shows it; report a vulnerability as `SECURITY.md` says;
- a contribution falls under the licence of the path it touches, as `NOTICE` says;
- a contributor from outside works from a fork and does not claim a task with a branch in the repository;
- checks that run code from an outside pull request start only after the maintainer approves them;
- only the maintainer sets the label `planner`.

`README.md` links it. `WORKER.md` says that its commit identity is for the project's own agents, and that anyone else uses their own name.

## Considered

- **Keep `library` as the only step.** It is the smallest proof that the toolchain works, but it shows no rule, no derived row and no witness, which is what Rezono is for.
- **Replace `library` with `subsidy`.** A failure in the larger example would then hide whether the toolchain works at all.
- **Publish the image.** It would be a release under another name; releases stay with the maintainer.
- **Keep the maintainer sections in the readme, lower down.** A newcomer scrolls past a wheel build, required checks and an alert policy before reaching the licence; each has a reader who looks for it elsewhere.
- **Put the Dependabot policy in `CONTRIBUTING.md`.** It would mix how to contribute with how alerts are answered; `SECURITY.md` already answers the second.
- **Show the output in prose instead of a `text` block.** Prose cannot be compared with what the command prints, so it drifts unseen.
- **Run the whole quickstart as one script and compare the total output.** One changed line would fail every step at once and not say which.
- **Build the image on every pull request.** It takes minutes and only the readme, the `Dockerfile` and the pinned requirements can break it.
- **Keep a single Datalog membership rule (`advised`) as the readme example.** It does not show a real calculation, an explicit `unknown` with its reason, or how a parameter links back to its article and council decision. Showing both `A001` and `A003` from `examples/subsidy` demonstrates known amounts with steps and explicit unknowns in one screen.
