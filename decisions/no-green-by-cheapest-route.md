---
decider: [loop, language, core]
decided_on: 2026-11-21
valid_from: 2026-11-21
state: in_force
subject: no-green-by-cheapest-route
---

# No green by the cheapest route: stricter tests, three shrinking budgets and pre-queue reading

A red test is a contract for the intended design, not a hurdle to clear by the shortest workaround. When a test checks only a loose textual proxy, permits a stopgap representation beside the target one, or leaves regression paths unguarded, an automated change can turn the suite green while undermining the architecture: citing a statute in a comment instead of in a witness, encoding dates as `YYYYMMDD` integers instead of native `date` values, duplicating source metadata blocks across records, or falling back to hand-written `.dl` files in a pack that already uses Rezono.

This decision establishes three rules to enforce **green along the intended route**: stricter planner tests, three monotonically shrinking shortcut budgets built on the shared `packs/std-budget` form ([tooling does not decide](tooling-does-not-decide.md#21-monotonically-shrinking-budget-packsstd-budget)), and a mandatory pre-queue reading review for example and red-test pull requests.

## 1. Stricter tests

Every planner red test and example test follows three invariants:

1. **Citations count only in structured proof or IR artifacts.** A statutory, policy or decision citation counts only when it appears in an emitted proof witness (`proofs.json` / `calc_sql.witnesses`), a compiled bundle rule or lowered `rezono.calc/1` calculation model entry (such as `bundle/schema-bundle.json` `rules[*].source` from [readable rules](language-readable-rules.md#2-the-sentence-and-the-source-at-the-rule) or `model.calc` / `calc.Program` definition override reasons from [ordered exceptions](language-exceptions.md)), or structured fact-origin metadata (`generated/sources.json`). Checking a citation as a raw substring in source text or comments is forbidden.
2. **Planner red tests never rely on workarounds.** A planner red test never introduces or accepts integer day numbers (`YYYYMMDD` / `*_day`) or hand-written Datalog (`.dl`) where the governing decision requires Rezono. When the language or compiler cannot yet express a needed construct — such as lowering `@` rule sources into `bundle/schema-bundle.json`, lowering inline versioned `param` declarations in `rezono_calc.py`, or native `date` comparisons in rules — the example test must depend explicitly on an existing language or compiler red test (or add a dedicated language red test) instead of accepting a shortcut.
3. **Every transitional test has a strict red retirement test beside it.** Whenever a staged migration requires a transitional test that accepts both an old and a new representation side by side, a strict `pytest.mark.xfail(strict=True, ...)` retirement test must be added beside it to enforce removal of the old representation.

As the immediate application, [the three-source healthcare allowance tests](../examples/test_zorgtoeslag_three_sources.py), [the healthcare allowance slice tests](../compiler/tests/rezono/test_zorgtoeslag_slice.py) and [the independent oracle](../examples/zorgtoeslag-slice/reference.py) remove all raw-text citation substring checks, `YYYYMMDD` / `*_day` day-number helpers and YAML/Datalog shortcuts, require `toeslagpartner`, `insured` and `joint_income` to live in Rezono modules under `examples/zorgtoeslag-slice/rezono/` with zero `.dl` files and zero `calc/*.yaml` files, keep inline versioned `param` declarations with `valid`, `known` and `@` sources across both first-slice and three-source forms, enforce native `date` and `Cents` types with zero `*_day` slots across the slice and all four source packs, verify `@ awr#art-5a`, `@ awir#art-3`, `@ wzt#art-2.1` and `@ wzt#art-2.2` in compiled `bundle/schema-bundle.json` rules, the lowered `rezono.calc/1` program (`model.calc` / `calc.Program`), rule proof witnesses and `calc_sql.witnesses`, pair the transitional single-source oracle branch with a strict red retirement test, and wait explicitly on the prerequisite language red tests. Similarly, [the platform support-window date retirement test](../examples/platform/test_support_window_dates.py) pairs the transitional `SupportQuery.as_of_day` stopgap of [standard packs everywhere](standard-packs-everywhere.md#11-what-is-there) with a strict red retirement test.

## 2. Three monotonically shrinking budgets (`packs/std-budget`)

Three shortcut metrics are governed by monotonically shrinking budgets instantiated in the shared Form 1 budget pack `packs/std-budget` ([tooling does not decide](tooling-does-not-decide.md#21-monotonically-shrinking-budget-packsstd-budget)):

- **Inputs to `packs/std-budget`:** `BudgetEntry(id, budget, cell, ceiling, revision)` and `BudgetReading(id, budget, cell, observed, revision)` with `revision` in `"base"` | `"head"`.
- **Blocking relations:** `budget_raised(budget, cell)`, `budget_exceeded(budget, cell)` and `budget_ratchet_violation(budget, cell)`. Growth on any ceiling, any new cell absent on base, any observed count above ceiling, or any base-to-head observed growth (even inside slack left behind by an earlier fix) is red — matching the shrink-only ratchet of `loop/red-decision-budget.json` ([decision-driven work](decision-driven-work.md)), `loop/decision-head-budget.json` ([decision heads](decision-heads.md)), `scripts/leak-budget.json` and `compiler/error-code-budget.json`.
- **Advisory relation:** `budget_slack(budget, cell)` hints that a listed ceiling may be lowered and never blocks.

### The three budgets

| Budget name | What is counted (thin reader in `loop/shortcut_budgets.py`) | Cell key | Blocking rule |
| --- | --- | --- | --- |
| `day_number_fields` | Integer day-number fields (`*_day` or `YYYYMMDD`-encoded integer `day` slots) in pack schemas (`schema/*.yaml` and `rezono/**/*.rezono` under `build/`, `examples/`, `packs/`, `run/`, excluding test fixtures and `candidate/`). Native `date`-typed slots and calendar-date kind references are not counted. | Pack path (e.g. `packs/std-decision`) | Growth or new cell is red |
| `duplicate_source_blocks` | Repeated identical source metadata blocks within a single `.sources.yaml` sidecar file: across `default` and `records` (stripping `of` from each record entry), each distinct source block occurring `n > 1` times in a file contributes `n - 1` repeated blocks. | `.sources.yaml` file path | Growth or new cell is red |
| `rezono_pack_dl_regression` | `.dl` files under `rules/` inside any pack or example (`pack.yaml` directory under `build/`, `examples/`, `packs/`, `run/`, excluding test fixtures) that **already has at least one Rezono module under `rezono/**/*.rezono`**. | Pack path (e.g. `examples/subsidy-scheme`) | Growth or new cell is red |

**Visible off-board migration tracking:** `.dl` files in packs that do **not** yet have any `rezono/**/*.rezono` module are not blocked by `rezono_pack_dl_regression`, because those packs have not yet migrated to Rezono. Instead, `loop/shortcut_budgets.py` reports them visibly as off-board migration work (`count_rezono_pack_dl_files(root)` returning `(regression_counts, offboard_counts)`). Once a pack introduces its first `rezono/*.rezono` module, any `.dl` file under its `rules/` falls under the shrinking regression budget so an example or pack that moved to Rezono can never backslide into Datalog.

### Thin reader and canonical budget file

- **Budget file:** `loop/shortcut-budget.json` is a canonical JSON object (2-space indent, sorted keys, trailing LF) mapping each of the three budget names above to a sorted `{cell: positive_int}` ceiling map.
- **Adapter (`loop/shortcut_budgets.py`):** Thin reader-only code `(d)` exposing:
  - `BUDGET_PATH = "loop/shortcut-budget.json"`
  - `count_day_number_fields(root: Path) -> dict[str, int]`
  - `count_duplicate_source_blocks(root: Path) -> dict[str, int]`
  - `count_rezono_pack_dl_files(root: Path) -> tuple[dict[str, int], dict[str, int]]`
  - `evaluate_shortcut_budget(budget_name: str, base_ceilings: dict[str, int], head_ceilings: dict[str, int], base_observed: dict[str, int], head_observed: dict[str, int]) -> dict[str, set[tuple[str, str]]]` — builds `BudgetEntry` and `BudgetReading` rows and derives `budget_raised`, `budget_exceeded`, `budget_ratchet_violation` and `budget_slack` strictly through `packs/std-budget` (no Python decision fallback, failing closed if `packs/std-budget` cannot evaluate).
  - `check_shortcut_budget(budget_name: str, root: Path, base: str | None = None) -> list[str]` — counts the working tree (and the `base` tree when provided), evaluates through `evaluate_shortcut_budget`, and returns blocking finding strings (empty when clean).

## 3. Pre-queue reading review

Every pull request that touches an example under `examples/` or adds, modifies or lifts a planner red test (`pytest.mark.xfail`) is read before entering the merge queue against its governing decision and [AGENTS.md](../AGENTS.md) ("green along the intended route"). Auto-merge is not enabled on such pull requests until the reading check confirms that no shortcut bypassed the decision's requirements.

This reading round complements [checker and access review](checker-and-access-review.md), which gates checker, canon, publisher, read-access and admission paths with commit-pinned `p1-read-<sha>` labels.

## 4. Considered alternatives

- **Block `.dl` files across every pack immediately.** Packs that have not yet started migrating to Rezono still need maintenance until their language prerequisites land. Separating `rezono_pack_dl_regression` (blocking on any pack that already has `rezono/*.rezono`) from the visible off-board count prevents backsliding without stalling unmigrated packs.
- **Implement the three budgets as bespoke Python scripts.** That would duplicate the monotonic ceiling and ratchet rules already consolidated in `packs/std-budget` by [tooling does not decide](tooling-does-not-decide.md).
- **Keep raw-text substring assertions for statutory citations until rule-source lowering lands.** A substring check accepts comments and uncompiled prose, creating a false green signal that masks whether citations actually reach witnesses and compiled IR. Waiting explicitly on the language red test keeps the test board honest.

## 5. Tests

- [loop/tests/test_shortcut_budgets.py](../loop/tests/test_shortcut_budgets.py): three strict `extra:` red tests covering `day_number_fields`, `duplicate_source_blocks` and `rezono_pack_dl_regression` (including visible off-board `.dl` counting and hand-worked growth/ratchet counter-cases evaluated through `packs/std-budget`).
- [examples/test_zorgtoeslag_three_sources.py](../examples/test_zorgtoeslag_three_sources.py) and [compiler/tests/rezono/test_zorgtoeslag_slice.py](../compiler/tests/rezono/test_zorgtoeslag_slice.py): tightened to forbid raw-text citation checks, `YYYYMMDD` / `*_day` day numbers, YAML fact workarounds, `calc/*.yaml` shortcuts and `.dl` fallbacks, preserving inline versioned `param` declarations, verifying structured citations in compiled `bundle/schema-bundle.json` rules, the lowered `rezono.calc/1` program (`model.calc` / `calc.Program`), rule proof witnesses and `calc_sql.witnesses`, and pairing the transitional single-source oracle branch with a strict red retirement test.
- [examples/platform/test_support_window_dates.py](../examples/platform/test_support_window_dates.py): strict `M3:` red retirement test enforcing removal of `SupportQuery.as_of_day` in favour of a native `date` slot (`as_of`) per [standard packs everywhere](standard-packs-everywhere.md#14-migration-order).
