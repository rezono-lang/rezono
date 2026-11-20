---
decider: [loop]
decided_on: 2026-11-20
valid_from: 2026-11-20
state: in_force
subject: decision-driven-work
---

# Derive work status per decision and require decision citations on red marks

Decisions already carry typed YAML heads that the build pack reads as [`std-decision`](../packs/std-decision/README.md) rows ([decision heads](decision-heads.md)), together with a citation scan (`BuildCitationScan`, `BuildDecisionCitation`, `BuildRedCitation`) that feeds `build_red_cites_replaced` and `build_uncited_decision` ([decision heads §4](decision-heads.md#4-the-heads-as-input-of-the-build-pack), [§5](decision-heads.md#5-two-rules-in-the-build-pack)). That tells reviewers when a red test cites a replaced decision or when an in-force decision is named nowhere, yet it still leaves two gaps: new red marks can omit the decision they implement, and neither the build pack nor the coordinator derives whether each in-force decision is currently open, untested, done or unknown.

This decision requires every added or edited red mark to cite an existing headed decision under a monotonically shrinking legacy budget, adds three status relations (`build_decision_open`, `build_decision_untested`, `build_decision_done`, plus the `build_decision_open_test` edge) to the build pack, defines how the coordinator reads `open` and `untested` work with its `decision -> test` chain, and orders the remaining headless-decision budget by citation priority. [Decision capture](../loop/build_decision_capture.py) · [Red guard](../scripts/red_guard.py) · [Red list](../scripts/red_list.py) · [Build reconciliation](build-reconciliation.md)

## 1. Every red mark's reason cites its decision

[`scripts/red_guard.py`](../scripts/red_guard.py) already requires every added or edited `pytest.mark.xfail` mark to be strict and to carry a literal `reason` starting with a milestone prefix (`M1: `, `M2: `, `M3: `, `M4: `, `extra: `, `later: `). This decision tightens that rule:

- **Mandatory headed-decision citation:** Any red mark that a change adds or edits (including any edit to its `reason` string) MUST name `decisions/<id>.md` immediately after the milestone prefix, followed by `:`, whitespace or end of string — for example `M3: decisions/<id>.md: ...` or `extra: decisions/<id>.md: ...`. Specifically, after stripping the milestone prefix, the text must match `decisions/([a-z0-9]+(?:-[a-z0-9]+)*)\.md(?::|\s|$)`.
- **Decision must exist and carry a valid head:** The named `decisions/<id>.md` MUST exist as a regular file in the reviewed head tree and carry a valid YAML decision head conforming to [decision heads §1](decision-heads.md#1-the-head). Missing decision files, headless decisions and decisions with malformed heads are refused, both with and without the `planner` label.
- **Standard-library check:** The test-evidence workflow runs `python -I scripts/red_guard.py` without third-party packages, so `scripts/red_guard.py` validates decision heads using only the Python standard library (`has_valid_decision_head(data)` and `decision_citation(mark)`).
- **Untouched legacy marks:** An untouched pre-existing red mark (same owner and identical AST, including unchanged `reason`) is not refused by the added/edited rule, as long as it remains within the budget below.

### Monotonically shrinking budget (`loop/red-decision-budget.json`)

Existing red marks whose reason does not yet cite a headed decision are listed in `loop/red-decision-budget.json`, using the exact same canonical format as [`loop/decision-head-budget.json`](../loop/decision-head-budget.json): a sorted JSON array of unique strings formatted with 2-space indentation and a single trailing LF (`json.dumps(sorted(set(entries)), indent=2) + "\n"`). Each entry identifies one legacy red mark as `<path>::<owner>`, matching the mark identifier reported by `scripts/red_guard.py` (for example `compiler/tests/test_example.py::test_feature`).

- **Shrink-only invariant:** `scripts/red_guard.py` checks any change to `loop/red-decision-budget.json` in `review(...)` (with or without `--planner`). Entries may only be removed compared to the base revision; adding an entry absent from the base budget or writing unsorted, duplicate or malformed JSON is refused.
- **No friction on lifting:** Removing entries from `loop/red-decision-budget.json` is permitted without the `planner` label and does not count as an unrelated protected change beside a lifted red mark, so a worker lifting a legacy red mark can retire its budget entry in the same pull request (or in a follow-up cleanup).
- **Review API:** `review(changes, planner=False, head=None, labels=(), packs=frozenset(), pins=frozenset(), head_tree=None)` validates every added or edited red mark against `head_tree` whenever `head_tree` (a `red_guard.Tree`) is supplied, and `check(base, head, ...)` always passes `head_tree=Tree.at(head)`.

## 2. Three derived decision-status relations in `build/`

[`build/rules/decision_rules.dl`](../build/rules/decision_rules.dl) reads the exact same verified cut scan (`BuildCitationScan`, `BuildDecisionCitation`, `BuildRedCitation` in [`build/schema/decision_rules.yaml`](../build/schema/decision_rules.yaml)), policy date (`build_policy_date_at_cut`), `std-decision` `in_force_on(decision, day)` and observed test-file inventory (`BuildTestFile` and `BuildComponent` in [`build/schema/selection.yaml`](../build/schema/selection.yaml)) used by `build_red_cites_replaced` and `build_uncited_decision`.

For every verified run `run` with a citation scan at the cut tick (`build_citation_scan_at_cut(run, scan)`) and a valid policy date (`build_policy_date_at_cut(run, day)`), the build pack derives and publishes:

1. **`build_decision_open_test(run, decision, test)`** and **`build_decision_open(run, decision)`** (`open`):
   - `build_decision_open_test(run, decision, test)` holds when `decision` is `in_force_on(decision, day)` and `scan` records a `BuildRedCitation` linking red test `test` to `decision`.
   - `build_decision_open(run, decision)` holds when at least one `build_decision_open_test(run, decision, test)` row exists. Its proof chains through the cut scan, the red citation and the decision's in-force proof.
2. **`build_decision_untested(run, decision)`** (`untested`):
   - Holds when `decision` is `in_force_on(decision, day)`, a cut scan exists (`build_citation_scan_at_cut(run, _)`), ZERO observed test files of `run` (`BuildTestFile` of a `BuildComponent` of `run`) have a `BuildDecisionCitation` naming `decision` in `scan`, and `decision` is not `build_decision_open(run, decision)`.
   - This relation is intentionally narrower than `build_uncited_decision(run, decision)`, which counts citations from any tracked file (documents, scripts, other decisions). A decision cited only in documentation or another decision is not uncited, yet it is still `untested`.
   - Resolving an `untested` row is planner work: either add a strict red test citing `decisions/<id>.md` (moving the decision to `open` for workers), or record in the decision why no automated test applies (or supersede/withdraw it if no longer active).
3. **`build_decision_done(run, decision)`** (`done`):
   - Holds when `decision` is `in_force_on(decision, day)`, a cut scan exists (`build_citation_scan_at_cut(run, _)`), at least one observed test file of `run` has a `BuildDecisionCitation` naming `decision` in `scan`, and `decision` is not `build_decision_open(run, decision)`.

All four relations are exported from [`build/rules/decision_rules.dl`](../build/rules/decision_rules.dl) with labels in `build/labels/en.yaml`. For any in-force headed decision at a scanned verified cut, `open`, `untested` and `done` are mutually exclusive and exhaustive. Decisions not in force on `day` (`proposed`, `superseded` once replaced, `withdrawn` or future `valid_from`) emit no row in any of these relations.

### Missing-scan safety

If `build_citation_scan_at_cut(run, scan)` does not hold — because no scan was captured for the slice, the scan's `observed_at` does not match the run's cut tick, its `source` is empty, or `build_verified_cut(run)` / `build_policy_date_at_cut(run, day)` fails — the rules emit **no row** in `build_decision_open`, `build_decision_open_test`, `build_decision_untested` or `build_decision_done`. Absence of a scan leaves every decision **`unknown`**, never `done`.

### Headless decisions in progress

Because `decision_rows` emits no `Decision` row for files without a YAML head ([decision heads §4](decision-heads.md#4-the-heads-as-input-of-the-build-pack)), headless decisions never appear in `build_decision_open`, `build_decision_untested` or `build_decision_done`. In milestone and decision progress reporting, every headless decision counts as **`unknown`**, never `done`.

### Working down `loop/decision-head-budget.json` by priority

[`loop/decision-head-budget.json`](../loop/decision-head-budget.json) is never worked down by guessing heads wholesale ([decision heads §6](decision-heads.md#6-decisions-without-a-head)). Instead, tracks work it down in priority order:

1. **`red-cited` (highest priority):** headless decisions named in the `reason` of at least one red test (`decisions/<id>.md`), ordered by descending red-test citation count and then by path.
2. **`headed-cited` (second priority):** remaining headless decisions named by at least one decision that already has a valid YAML head (either via `decisions/<id>.md` or a relative link `](<id>.md`), ordered by descending headed-decision citation count and then by path.
3. **`other`:** all remaining headless decisions in the budget, ordered alphabetically by path.

## 3. Coordinator reads `open` and `untested` rows

Alongside the red board, the coordinator reads the published decision-status relations through a thin reader module, `loop/build_decision_work.py`, so both worker work (`open`) and planner work (`untested`) carry an explicit decision reason chain:

- **`read_decision_work(*, run, manifest, rows, headless_decisions=(), known_decisions=())`:**
  - Checks that `manifest` is present and every check in `manifest["checks"]` has `status == "green"`, and that `rows` contains `build_decision_open`, `build_decision_open_test`, `build_decision_untested` and `build_decision_done` with well-formed keys belonging to `run` (malformed rows or foreign-run rows raise `ValueError`).
  - When `manifest` or `rows` is missing, unverified or incomplete, returns `verified=False`, empty `worker_tasks`, empty `planner_tasks`, empty `done`, and places every decision in `known_decisions` and `headless_decisions` into `unknown` (never `done`).
  - When verified:
    - Emits one **`worker_tasks`** item per `(decision, test)` row in `build_decision_open_test` (sorted by `(decision, test)`), carrying `role="worker"`, `status="open"`, `decision`, `decision_path="decisions/<id>.md"`, `test` and `reason="decisions/<id>.md -> <test>"`. Every `build_decision_open` row must be backed by at least one `build_decision_open_test` row (otherwise `ValueError`).
    - Emits one **`planner_tasks`** item per `decision` in `build_decision_untested` (sorted by `decision`), carrying `role="planner"`, `status="untested"`, `decision`, `decision_path="decisions/<id>.md"`, `test=None` and a `reason` naming `decisions/<id>.md`.
    - Places `build_decision_done` ids into `done`, refusing with `ValueError` if any headless decision appears in `done`.
    - Places every headless decision (from `headless_decisions`, normalized to its decision id) and every decision in `known_decisions` absent from `open`, `untested` and `done` (for example after a missing scan) into `unknown`.
    - Returns `progress = {"open": ..., "untested": ..., "done": ..., "unknown": ...}` alongside `open`, `untested`, `done` and `unknown`.
- **`prioritize_headless_decisions(root, budget_paths, red_tests)`:**
  - Scans headed decisions under `root/decisions/` and `red_tests` (`{"id": ..., "reason": ...}` items as from `scripts/red_list.py --json`), and returns the budget entries ordered by the three tiers of section 2 (`red-cited`, `headed-cited`, `other`), each with `path`, `decision`, `tier`, `red_tests` and `headed_decisions`.

## 4. Deferred scope (not now)

Only once the red-mark citation guard, the three derived decision-status relations and the coordinator reader are proven in daily operation should the following extensions be considered:

- **Typed dependency edges between decisions (`depends_on`, `supersedes`) for task ordering:** ordering work across decisions by dependency graph belongs in a later decision once basic per-decision status (`open`, `untested`, `done`, `unknown`) is reliable.
- **Representing owner priorities as decisions:** expressing track and owner priority overrides as decision records is deferred until decision-driven work routing is established.

## 5. Alternatives considered

- **Reuse `build_uncited_decision` as `untested`.** `build_uncited_decision` clears as soon as any document or other decision links to a decision, which hides in-force decisions that have zero test coverage. Joining `BuildDecisionCitation` with the run's observed `BuildTestFile` inventory separates documentation references from test coverage without changing `BuildDecisionCitation`'s schema or breaking `citation_rows`.
- **Add an `is_test` field to `BuildDecisionCitation` instead of joining `BuildTestFile`.** That would duplicate the suite test-file inventory already observed by `BuildTestFile` and require changing every existing `BuildDecisionCitation` producer and test fixture.
- **Default unscanned or headless decisions to `done`.** That would turn missing observations or unmigrated decisions into false completion signals. Keeping both `unknown` preserves fail-closed progress reporting.
- **Require PyYAML inside `scripts/red_guard.py`.** The policy workflow runs `python -I scripts/red_guard.py` in a minimal stdlib environment; validating the restricted flat YAML head grammar of [decision heads §1](decision-heads.md#1-the-head) with the standard library keeps the guard self-contained and isolated.
- **Backfill all red marks and decision heads in one pull request.** Mass-editing hundreds of legacy marks or guessing heads wholesale risks inaccurate citations and merge conflicts; monotonically shrinking budgets (`loop/red-decision-budget.json` and `loop/decision-head-budget.json`) stop new debt immediately while letting each track retire existing entries accurately.
