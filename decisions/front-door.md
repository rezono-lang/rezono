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

Someone who opens the repository sees, in the first screen, what Rezono does, what sets it apart, and one example with its facts, rules, answer and proof. Everything for maintainers lives elsewhere. `README.md` has at most 180 lines (raised from 150 to hold the language subsection in `## Example`, as explained below) and exactly these seven parts, in this order, under these headings:

1. **`# Rezono`.** One sentence of at most 25 words that says in plain words what Rezono does. It says what the repository's About says: *Facts and rules in, answers with proof out. Every conclusion carries a witness an independent checker verifies.*
2. **`## What you get`.** At most five short lines, each naming something that works at this commit.
3. **`## Example`.** Before the first command: a worked calculation from `examples/subsidy` (replacing the earlier requirement of a single Datalog rule copied from the pack's rule files). A `yaml` block shows a few facts from `examples/subsidy/facts/*.yaml` (including `A001` and `A003`), a `### The rules in Rezono` subsection shows two calculation rules from the imported scheme in Rezono together with a one-line compiler refusal and the four value states (see [The language in the readme](#the-language-in-the-readme)), and a `text` block at the end of the section shows two answers in plain words and euro amounts, with no hash and no path:
   - **`A001`:** the award (€ 2,694: cost share € 2,544 at the 24% partial rate for income € 31,400 between the € 30,000 threshold for 3 persons and the € 42,000 limit, plus € 150 advice allowance) and the calculation steps it rests on, each step naming its calculation rule, version, evaluation date, definition and parameter; plus the article and council decision of a read parameter (from the parameter row, printed by a second `jq` in step 2).
   - **`A003`:** the derived `assessment` row (`unknown`, reason `income_statement_not_received`) and an unknown calculated award (never zero). Because the example's separate payment ledger did record a payment for `A003`, the wording states explicitly that the *calculated award* is unknown while the income statement is missing, so a reader who later inspects the ledger is not misled.

   One sentence states that the independent checker verified the witness before publication and that an independent computation (`examples/subsidy/reference.py`) produces the same amount. The `text` block appears word for word in the `text` block under step 2 of the quickstart.
4. **`## Try it`.** The quickstart steps, each `bash` block followed by a `text` block with the output it prints, and the two container commands in an `sh` block.
5. **`## Read further`.** Links to the tutorial (`docs/tutorial.md`), the language guide (`rezono/README.md`), the examples (`examples/`) and `docs/vision.md`.
6. **`## Status`.** "There is no release yet.", and what works at this commit.
7. **`## Licences and contributing`.** Two lines: one that links `LICENSE`, `LICENSES/` and `NOTICE`, one that links `CONTRIBUTING.md`.

Sections may have `###` subheadings, such as `### The rules in Rezono` inside `## Example` and one per quickstart step; no other `##` heading appears.

## The language in the readme

A reader opening the repository should see Rezono itself before the first command, using only what compiles and runs at this commit.

- **Placement.** The language part is a `###` subheading (`### The rules in Rezono`) inside `## Example`, between the `yaml` facts block and the `text` answers block. That keeps the seven top-level parts intact, preserves the `yaml`-first and `text`-last fence layout of `## Example`, and follows the opening sentence in order: facts in, rules in, answers with proof out.
- **Line ceiling and what gives way.** Before adding the language subsection, `README.md` uses 124 of its 150 lines; nearly all of those lines are checked `yaml`, `bash`, `text` and `sh` blocks plus the four required `## Read further` links. Nothing tested is dropped: the Docker commands, the two quickstart steps, the checked `A001`/`A003` output and all four links stay. To avoid bloat, prose in `## Example` does not re-explain in words what the shown Rezono rules already state, and `## What you get` stays within five short lines. Because adding two fenced language blocks (at most 20 lines each) plus their framing sentences cannot fit in the 26 remaining lines without cutting tested content, the `README.md` line ceiling rises from 150 to 180 lines (leaving headroom for the planned third quickstart step).
- **Literal excerpt of two `A001` calculation rules.** The first language block is at most 20 lines, copied byte for byte (preserving source indentation so it matches a contiguous slice of lines) from a `.rezono` source file declared under `rezono:` in `pack.yaml` — never under `candidate/` — of `examples/subsidy` or a pack it imports. Specifically, once `examples/subsidy-scheme` replaces `calc/award.yaml` with `rezono/award.rezono` declared in `examples/subsidy-scheme/pack.yaml`, the excerpt quotes the two contiguous calculation rules **`entitlement`** and **`award`** from `examples/subsidy-scheme/rezono/award.rezono`. Both rules appear in `A001`'s `text` output block (`award € 2,694` and `entitlement € 2,694`). One sentence links to that source file (`examples/subsidy-scheme/rezono/award.rezono`) for the other calculation rules (`income_threshold`, `income_limit`, `cost_share`, `advice_allowance`).
- **One-line change and compiler refusal (`R050`, `ambiguous leaf`).** A second language block shows the same excerpt with **one line changed**: inside `derived entitlement`, `Application.advice_allowance` is written bare as `advice_allowance`. Because `examples/subsidy-scheme` declares both a row-backed parameter `advice_allowance` and a derived calculation rule `advice_allowance` on `Application`, the compiler refuses the pack with **`R050`** (`ambiguous leaf 'advice_allowance'`) before any calculation runs, rather than silently choosing one. Prose beside the block names the refusal and its code `R050`.
  - Why `R050` rather than a unit error (`R003`): in `examples/subsidy-scheme`, calculation inputs come from derived relation columns (`assessed_income.cents`, `assessed_costs.cents`) and row-backed parameters (`SchemeParameter.value`), and `cents` is not a declared unit in the pack's unit table; the compiler does not yet check units on those leaves, so `R003` is not reachable in `award`. `README.md` makes no claim about a unit check the compiler does not perform.
- **Four value states.** One sentence in `## Example` states that every calculated value is `known`, `unknown` (with a reason), `not_applicable` or `invalid`, and that Rezono never silently picks a fallback.
- **Fence label `haskell` and no image in `README.md`.** Both Rezono blocks in `README.md` (and the first code block of `rezono/README.md`) use a plain fenced code block with the label `haskell`. GitHub colours code blocks through Linguist, which requires roughly two hundred public repositories before recognizing a language, so a `rezono` fence renders uncoloured on GitHub. Tested against GitHub's Markdown renderer, `haskell` highlights comments (`--`), type names (`Int`, `Application`), numbers, operators and keywords such as `then` and `else`, while leaving Rezono-specific keywords (`derived`, `unit`, `version`, `definition`, `when`) plain rather than mis-highlighted. Labels such as `python` and `ruby` treat `#` as a comment and mis-highlight Rezono. Keeping a plain code fence leaves the excerpt copyable and searchable; `README.md` carries no image (light/dark SVG highlighting belongs in `rezono/README.md`).
- **No premature `rezono 1` mention.** While the quoted pack is authored in `rezono 0`, `README.md` does not mention `rezono 1`; updating the readme for `rezono 1` follows once the quoted pack moves to `rezono 1`.

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
- **Give the language excerpt its own top-level `##` section.** Adding an eighth top-level heading breaks the seven-part front-door layout and separates the rules from the facts and answers they connect. Placing `### The rules in Rezono` inside `## Example` keeps one narrative from facts to rules to answers.
- **Hold the 150-line ceiling by dropping the Docker `sh` block or trimming the checked `A001` output.** Both are tested front-door guarantees; raising the ceiling to 180 lines keeps them intact while still bounding `README.md` to one concise page.
- **Demonstrate a unit error (`R003`) in the subsidy calculation.** In `examples/subsidy-scheme`, calculation leaves come from derived relation columns and row-backed parameters whose units the compiler does not yet check, so `R003` is unreachable in `award`. `R050` (`ambiguous leaf`) is genuinely enforced by the compiler on `award` today.
- **Use a `rezono`, `python` or `ruby` fence, or embed an SVG image in `README.md`.** `rezono` renders uncoloured on GitHub; `python` and `ruby` treat `#` as a comment; an image cannot be copied. `haskell` highlights cleanly and remains copyable, while `rezono/README.md` hosts the light/dark SVG image.
