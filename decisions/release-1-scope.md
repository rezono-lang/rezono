---
decider: [owner]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: release-1-scope
---

# Release 1 is the milestone path: the table twin with why, the local what if, engine agreement and the language at the front door

The [vision](../docs/vision.md) promises more than the first public release can hold, and until now no file said which part of it that release carries. The marks at the start of a red test's reason order the work ([worker card](../WORKER.md)): a worker takes `M1` to `M4` before `extra`, and `later` is not a task. But no file said what each mark means, and every red test of Reading, of What if and of engine agreement on witnesses carried `extra:` or `later:`. So did every red test that puts the language in the readme and the language guide. So the board planned none of them for the release. This decision defines the marks, says which parts of the vision and of the front door release 1 carries, and moves the red tests of those parts onto the milestone path. The owner adopted it as advice from an audit of the vision, added the language at the front door the same day, and then confirmed the whole scope as written here, following the advice on every choice it put to them. [Worker card](../WORKER.md) · [The slip](viewer-slip.md) · [What if, locally](local-suppose.md) · [EPL-2.0 and generic views](runtime-epl-and-generic-views.md) · [Rezono 1](language-rezono-1.md) · [Feldera calculation parity](feldera-calculation-parity.md) · [The front door](front-door.md) · [Language guide highlight](language-guide-highlight.md)

## 1. What the marks mean

No earlier file defines them. `scripts/red_list.py` and `scripts/red_guard.py` know the six marks and their order, the worker card says how a worker chooses by them, and [the five scenes](platform-five-scenes.md) orders the work within one milestone. The meaning below is the one the marks on `main` already follow.

| Mark | Meaning | Where it stands today |
| --- | --- | --- |
| `M1` | The foundation: every derived row with a witness and an independent checker, exact values, explicit unknown, a publication per role, and a compiled publication with one canonical hash. | Built. No red test carries it. |
| `M2` | The reference platform in its five scenes, and the loop that applies a plan and reads it back. | `examples/platform/`, `loop/tests/`. |
| `M3` | Rezono 1, the language of the first release, and the language where a newcomer first meets it; the engines that run it, which agree; and the reader: the slip, the what-if answer and turning points. | [Rezono 1](language-rezono-1.md), [Feldera calculation parity](feldera-calculation-parity.md), and the parts in sections 3 to 7. |
| `M4` | Runs against live providers. | `run/tests/`. |
| `extra` | Specified and wanted, not needed for release 1. A worker takes it after `M1` to `M4` of its area. | |
| `later` | Not a task. It waits for a decision, an outside dependency, or a release after the first. | |

- **Release 1 is the milestone path.** It carries what `M1` to `M4` mark, and it is complete for its scope when no red test carries one of them. `python scripts/red_list.py --milestones` shows how far it is.
- **A test is never on an earlier milestone than a test it waits for.** A reason that says "Waits for" another test names one on the same milestone or an earlier one, so a worker who takes the earliest mark is never stopped by a task that comes later. That is why sections 3 and 6 move some tests that are not themselves the part they serve.
- **Moving a mark is planner work.** A planner moves a red test onto the milestone path, or off it, in a pull request that names the decision. `scripts/red_guard.py` refuses a postponed mark without the planner label. It lets a changed reason move to an earlier milestone, because a worker who extends a reason keeps its mark (worker card, "If it does not work"); a worker does not move it.
- **Only the mark changes.** The rest of a reason says what to build and stays as its planner wrote it.

## 2. What release 1 carries from the vision

| Vision | Release 1 |
| --- | --- |
| Proof | Built (`M1`), except that the two engines agree on conclusions and witnesses: section 6. |
| Exact and deterministic, Unknown is explicit | Built (`M1`). |
| Access | Built (`M1`). The hardening the audit found on `extra` (the checker's own reading of a role bundle and of an access change, `may_read_full`, the rights to propose and review, the partial reader of the edge pilot profile) landed on `main` on the day of this decision. |
| What if | The local answer with weights `+1` and `−1` and a witness per row, observations that do not change, and turning points with the proof on both sides (section 5). |
| The loop | `M2`. |
| Two kinds of comparison | Not changed by this decision. |
| Reading | The table twin with its legend, the verbs why and depends on the slip, and the key of signs in the publication (sections 3 and 4). Not the drawing views, missing, compare or propose (section 8). |

Beside the vision, release 1 carries the language at the front door: the readme and the language guide show rules that compile and run at the commit (section 7).

## 3. Reading: the table twin, its legend and why

Release 1 has one sheet: the slip of [the slip decision](viewer-slip.md), step 1, as far as a reader needs it to see one conclusion as a table with a legend and to ask why. That is the page, the parts of the local reader the page asks, and the rows the page must draw: a rule row, a calculated row and a value that is not known. A calculated row is in, because the calculations of Rezono 1 are the conclusions most readers ask about, and `test_tables_and_legend` already draws one. A value that is not known is in, because a page that draws it with a digit breaks "Unknown is explicit".

These red tests move from `extra` to `M3`:

- `tests/slip/test_role_part_of_bundle.py::test_role_part_of_bundle`
- `tests/slip/test_head_status_and_hash.py::test_head_status_and_hash`
- `tests/slip/test_message_filled.py::test_message_filled`
- `tests/slip/test_slip_rule_row.py::test_slip_rule_row`
- `tests/slip/test_slip_calculated_row.py::test_slip_calculated_row`
- `tests/slip/test_unknown_shows_no_digit.py::test_unknown_shows_no_digit`
- `tests/slip/test_verbs_that_answer.py::test_verbs_that_answer`
- `tests/slip/test_tables_and_legend.py::test_tables_and_legend`

The rest of step 1 stays `extra`: `tests/slip/test_unserved_publication.py::test_unserved_publication`, because the local reader already refuses a damaged witness set and the page's own notice of it comes after, and `examples/test_slip_claims.py::test_one_build_every_claim`, because release 1 needs the page, not a home claim drawn for every example. Step 2 on the page (`test_several_sweeps`, `test_several_sweeps_in_the_repl`, `test_variant_difference_local`, `test_stops_only`) stays `extra`: release 1 answers what if through the reader (section 5), not yet through a control on the line. Steps 3 to 5 have no tests yet.

## 4. The key of signs

The vision says a publication carries the key of signs. Today it does not: the schema bundle carries the pack's own part of the key (`channels`), and [the slip decision](viewer-slip.md#the-verbs) says that the viewer build takes `std-view` in and that no pack publishes it. A reader that holds only a publication then cannot read its signs, and nothing binds the signs a page draws to the hash of what it shows.

**The key of signs is published.** Every schema bundle the compiler writes carries it, whatever the pack imports:

- a part `key` with the `statuses`, `tones`, `signs` and `differences` of `packs/std-view/key.yaml`, entry for entry and in their order there;
- in the bundle's `messages`, the label each of those entries names, in every language of `std-view`, as `packs/std-view/messages` has it.

The bundle is archived with its hash in the manifest's `compiled` list, so the manifest's hash covers the key. It holds no fact, so every role may read it. Colours stay out: no sign depends on colour, and a house style changes colours, never a sign. The sheets, the verbs and the palette of `std-view` stay in the viewer build; where [the slip decision](viewer-slip.md#the-verbs) says that no pack publishes `std-view`, that now holds for those and not for the key of signs.

Red test, `M3`: `tests/slip/test_key_of_signs_published.py::test_key_of_signs_published`. It publishes `tests/fixtures/slip`, which does not import `std-view`, reads the bundle the manifest names, and takes its expectation from `packs/std-view` itself.

## 5. What if

Release 1 answers "what if" on the batch engine with the command of [What if, locally](local-suppose.md), and gives turning points with the proof on both sides as [the slip decision](viewer-slip.md#turning-points) defines them: computed by the publisher, recomputed by the checker, written per pair of neighbouring stops, and served by `sweep`. Without the last step a turning point is a function no reader can ask.

These red tests move from `extra` to `M3`:

- `examples/subsidy/test_local_suppose.py::test_a_local_assumption_moves_the_awards_as_the_reference_does`
- `examples/subsidy/test_local_suppose.py::test_every_row_of_an_assumption_has_a_weight_and_a_witness`
- `examples/subsidy/test_local_suppose.py::test_an_award_that_becomes_unknown_is_answered_with_its_reason`
- `examples/subsidy/test_local_suppose.py::test_an_assumption_that_may_change_access_gives_no_difference`
- `edge/publisher/tests/test_turning_points.py::test_turning_points`
- `checker/tests/test_turn_check.py::test_turning_points_checked`
- `tests/slip/test_turn_unknown_neighbour.py::test_turn_unknown_neighbour`

"Observations do not change under an assumption" is in release 1 as well. [What if, locally](local-suppose.md) fixes it: a delta that changes a kind whose bundle layer is `observation` is refused with that reason. No red test checks it yet; the planner who writes it marks it `M3`. An assumption that is not on a grid, and a supposition through the hosted gate (`blocked/edge-gate-hosted.txt`), stay outside.

## 6. Engine agreement

The two engines must agree on conclusions and on witnesses. The incremental engine has no green run on `main` yet ([What if, locally](local-suppose.md#considered)), and no test compares a calculation's reasons or witnesses on it in a real pack ([Feldera calculation parity](feldera-calculation-parity.md)). `examples/test_calculation_engine_parity.py::test_feldera_calculations_match_duckdb_and_checker` is already `M3`. The two tests that close the live comparison wait for it and for the routing of `compiler/tests/test_recorded_dates.py::test_independent_date_equality`, so all three move from `extra` to `M3`:

- `compiler/tests/test_recorded_dates.py::test_independent_date_equality`
- `examples/test_live_feldera_shards.py::test_merge_preserves_all_live_cases_and_outcomes`
- `examples/test_feldera_incident.py::test_classifier_uses_complete_reports_from_the_parallel_comparison`

Release 1 says that the engines agree only when these four are green.

## 7. The language at the front door

A newcomer meets Rezono in the root `README.md` and in the language guide `rezono/README.md`. [The front door](front-door.md) lets the readme show only what compiles and runs at the commit. Release 1 carries the language at the front door, in this order:

1. **The first real pack on the live path in Rezono.** `examples/subsidy-scheme` replaces `calc/award.yaml` with the module `rezono/award.rezono`, declared under `rezono:` in its `pack.yaml`, with the same `ir/calc.json` and the same outcomes under `expected/calc/` of `examples/subsidy` ([calculations in Rezono](language-calculations.md)). Its test (`examples/subsidy/test_subsidy_scheme_award.py::test_subsidy_scheme_award_in_rezono`) is already green on `main`.
2. **The rules in the readme.** `### The rules in Rezono` under `## Example`, as [the front door](front-door.md#the-language-in-the-readme) specifies: a literal excerpt of two `A001` rules, the same excerpt with one changed line beside its `R050` refusal, and one sentence that names the four value states. Each of its tests waits for step 1.
3. **The language guide opens with the language.** `rezono/README.md` starts with a copyable excerpt of `examples/subsidy-scheme/rezono/award.rezono`, and its light and dark highlighted SVG with a colour legend ([language guide highlight](language-guide-highlight.md)). Its tests wait for step 1 and for `rezono/test/test_rezono_syntax_grammar.py::test_generated_syntax_highlighting_grammar`, which is green, as is the theme that colours every token kind (`test_highlight_theme_covers_every_token_kind_in_light_and_dark`).

All three steps landed on `main` on the day of this decision, so their tests are green and this decision moves none of them: the three in `examples/test_readme_layout.py`, `rezono/test/test_language_guide_excerpt.py::test_language_guide_starts_with_subsidy_award_excerpt` and the four in `rezono/test/test_language_guide_highlight.py`. They stay part of release 1: a change that takes the language off the front door again fails them.

An excerpt follows the language version of the pack it quotes: while `award.rezono` is written in `rezono 0`, the readme does not mention `rezono 1` ([the front door](front-door.md#the-language-in-the-readme)).

**The quickstart asks.** Step 2 of the quickstart shows the answer for `A001` with an `ask`, in the REPL or as a command, instead of `jq`, so that a newcomer reads a question put to Rezono rather than a query on its files. It is part of release 1. It changes [the front door](front-door.md#the-quickstart-computes), which asks for a second `jq` and a final `jq -e` that names `witness`, so a planner pull request of its own changes that decision and writes the red test, marked `M3`. This decision moves no test for it.

## 8. What stays outside release 1

- **Drawn views with positions** (`later: tekenweergaven`). [EPL-2.0 and generic views](runtime-epl-and-generic-views.md) already puts published positions and the drawing views after the first installable release. They need a layout engine and positions in the publication; the table twin reads the same rows without them.
- **Hosted identity and the gate** (`blocked/edge-gate-hosted.txt`, `blocked/edge-gate-variant-queries.txt`, `blocked/edge-gate-indexed-publications.txt`, `blocked/edge-gate-inheritance-ask.txt`, `blocked/edge-gate-other-publication-routes.txt`). Release 1 reads through the local reader, for the role its caller chooses, on the loopback address. Sign-in, visitor access and writes through the gate are a hosted service, which [the slip decision](viewer-slip.md#out-of-scope) leaves out too.
- **The verbs missing, compare and propose on a page** (step 4 of the slip). They need questions the local reader does not answer yet, and propose needs the gate. A reader that answers one more question makes one more verb appear without a change to the page, so they can come after release 1 without a new page.

## Alternatives

- **Leave the marks as they are.** Workers would reach Reading and What if only after every `M` test, so the release would come without them while the vision promises both.
- **A mark of its own for release 1, or a list of release tests.** `red_list.py` and `red_guard.py` know six marks and their order; a seventh changes the policy and every planner's reading. A list would be one more file that every pull request must touch (root `AGENTS.md`, "One file per thing").
- **Put the reader on `M2`.** `M2` is the platform and the loop; the reader serves every pack. `M3` keeps it beside the language and the engines whose rows it reads.
- **All of steps 1 and 2 of the slip.** That is more than the owner chose. The what-if control on the line waits for several sweeps and the variant difference in the local reader; the reader's answer and turning points give what if without it.
- **Leave the front door for after release 1.** The readme would show facts and answers but not one line of the rules between them, and the language guide would open with a table of source files: a first release of a language that its own front door does not show.
- **Keep the key of signs in the viewer build.** A page would draw signs that nothing in the publication binds, and another view would have to fetch `std-view` on its own.
