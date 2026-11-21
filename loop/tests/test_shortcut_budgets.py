"""Three monotonically shrinking shortcut budgets instantiated in the shared `packs/std-budget`
form (decisions/no-green-by-cheapest-route.md, decisions/tooling-does-not-decide.md §2.1):

1. `day_number_fields`: integer day-number schema fields (`*_day` or `YYYYMMDD` integer `day` slots)
   in pack schemas (native `date` slots are not counted).
2. `duplicate_source_blocks`: repeated identical source metadata blocks within a `.sources.yaml`
   sidecar file (comparing source blocks with `of` excluded across `default` and `records`).
3. `rezono_pack_dl_regression`: `.dl` files under `rules/` in any pack or example that already has
   at least one Rezono module (`rezono/**/*.rezono`), paired with visible off-board tracking of `.dl`
   files in packs that have not yet introduced a `rezono/` module.

Each test exercises the real repository budget and hand-worked counter-cases (ceiling excess, raised
ceiling, new cell, and within-slack ratchet growth) evaluated through `packs/std-budget`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "packs"
STD_BUDGET = PACKS / "std-budget"
BUDGET_FILE = ROOT / "loop" / "shortcut-budget.json"


def _load_shortcut_budgets():
    assert (STD_BUDGET / "pack.yaml").is_file(), "packs/std-budget does not exist yet"
    assert BUDGET_FILE.is_file(), "loop/shortcut-budget.json does not exist yet"
    raw = BUDGET_FILE.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, indent=2, sort_keys=True) + "\n", (
        "loop/shortcut-budget.json must be canonical sorted JSON with 2-space indent and trailing LF"
    )
    try:
        import shortcut_budgets
    except ImportError as exc:
        raise AssertionError(f"loop/shortcut_budgets.py does not exist yet: {exc}") from exc
    return shortcut_budgets, parsed


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: Implement the monotonically shrinking "
           "`day_number_fields` budget in loop/shortcut_budgets.py and loop/shortcut-budget.json "
           "evaluated through packs/std-budget so integer *_day / YYYYMMDD schema fields can only "
           "shrink and growth or a new cell is refused. "
           "Waits for loop/tests/test_tooling_does_not_decide.py--test_monotonically_shrinking_budget_shared_form.",
)
def test_day_number_schema_fields_budget_only_shrinks(tmp_path: Path):
    sb, budget = _load_shortcut_budgets()
    assert sb.BUDGET_PATH == "loop/shortcut-budget.json"
    assert "day_number_fields" in budget and isinstance(budget["day_number_fields"], dict)
    assert sb.check_shortcut_budget("day_number_fields", ROOT) == []

    # Hand-worked counter-case tree:
    # - packs/p-legacy has 2 integer day-number slots (`valid_from_day`, `day` YYYYMMDD) plus 2 native date
    #   slots (`valid_from: date`, `cal: CalendarDate`) that must NOT be counted.
    # - examples/p-rezono has 1 integer day-number slot (`issued_on_day: Int`) plus 1 native `Date` slot.
    _write(
        tmp_path / "packs" / "p-legacy" / "pack.yaml",
        "name: p-legacy\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tmp_path / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\n"
        "name: p_legacy\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      valid_from: {range: date}\n"
        "      valid_from_day: {range: integer, description: 'valid_from as YYYYMMDD'}\n"
        "      day: {range: integer, description: 'The day as whole number YYYYMMDD'}\n"
        "      cal: {range: CalendarDate}\n",
    )
    _write(
        tmp_path / "examples" / "p-rezono" / "pack.yaml",
        "name: p-rezono\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tmp_path / "examples" / "p-rezono" / "rezono" / "model.rezono",
        "rezono 1\npack p-rezono\n\nkind Note\n  issued_on: Date\n  issued_on_day: Int\n",
    )

    counts = sb.count_day_number_fields(tmp_path)
    assert counts == {"examples/p-rezono": 1, "packs/p-legacy": 2}, counts

    # Evaluated via packs/std-budget: steady and shrinking pass; ratchet growth, excess, raised ceiling fail.
    steady = sb.evaluate_shortcut_budget(
        "day_number_fields",
        base_ceilings={"examples/p-rezono": 1, "packs/p-legacy": 2},
        head_ceilings={"examples/p-rezono": 1, "packs/p-legacy": 2},
        base_observed={"examples/p-rezono": 1, "packs/p-legacy": 2},
        head_observed={"examples/p-rezono": 1, "packs/p-legacy": 2},
    )
    assert steady["budget_raised"] == set()
    assert steady["budget_exceeded"] == set()
    assert steady["budget_ratchet_violation"] == set()

    shrunk = sb.evaluate_shortcut_budget(
        "day_number_fields",
        base_ceilings={"packs/p-legacy": 2},
        head_ceilings={"packs/p-legacy": 2},
        base_observed={"packs/p-legacy": 2},
        head_observed={"packs/p-legacy": 1},
    )
    assert shrunk["budget_raised"] == set()
    assert shrunk["budget_exceeded"] == set()
    assert shrunk["budget_ratchet_violation"] == set()
    assert ("day_number_fields", "packs/p-legacy") in shrunk["budget_slack"]

    # Growth inside slack (base observed 1 -> head observed 2, ceiling still 2) is a ratchet violation.
    ratchet = sb.evaluate_shortcut_budget(
        "day_number_fields",
        base_ceilings={"packs/p-legacy": 2},
        head_ceilings={"packs/p-legacy": 2},
        base_observed={"packs/p-legacy": 1},
        head_observed={"packs/p-legacy": 2},
    )
    assert ("day_number_fields", "packs/p-legacy") in ratchet["budget_ratchet_violation"]

    # Exceeding ceiling or raising ceiling / adding a new cell is refused.
    grew = sb.evaluate_shortcut_budget(
        "day_number_fields",
        base_ceilings={"packs/p-legacy": 2},
        head_ceilings={"packs/p-legacy": 3, "examples/p-new": 1},
        base_observed={"packs/p-legacy": 2},
        head_observed={"packs/p-legacy": 4, "examples/p-new": 1},
    )
    assert ("day_number_fields", "packs/p-legacy") in grew["budget_raised"]
    assert ("day_number_fields", "examples/p-new") in grew["budget_raised"]
    assert ("day_number_fields", "packs/p-legacy") in grew["budget_exceeded"]
    assert ("day_number_fields", "packs/p-legacy") in grew["budget_ratchet_violation"]
    assert ("day_number_fields", "examples/p-new") in grew["budget_ratchet_violation"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: Implement the monotonically shrinking "
           "`duplicate_source_blocks` budget in loop/shortcut_budgets.py and loop/shortcut-budget.json "
           "evaluated through packs/std-budget so repeated identical source blocks inside .sources.yaml "
           "files can only shrink and growth or a new cell is refused. "
           "Waits for loop/tests/test_tooling_does_not_decide.py--test_monotonically_shrinking_budget_shared_form.",
)
def test_duplicate_source_blocks_budget_only_shrinks(tmp_path: Path):
    sb, budget = _load_shortcut_budgets()
    assert "duplicate_source_blocks" in budget and isinstance(budget["duplicate_source_blocks"], dict)
    assert sb.check_shortcut_budget("duplicate_source_blocks", ROOT) == []

    # Clean file: shared block once in `default:`, distinct record positions -> 0 duplicates.
    _write(
        tmp_path / "examples" / "alpha" / "facts" / "clean.sources.yaml",
        "default:\n"
        "  kind: git\n"
        "  name: rezono-lang/rezono\n"
        "  revision: 0000000000000000000000000000000000000001\n"
        "  position: decisions/example.md\n"
        "records:\n"
        "  - of: {kind: item, id: a}\n"
        "    kind: git\n"
        "    name: rezono-lang/rezono\n"
        "    revision: 0000000000000000000000000000000000000001\n"
        "    position: decisions/example.md#a\n"
        "  - of: {kind: item, id: b}\n"
        "    kind: git\n"
        "    name: rezono-lang/rezono\n"
        "    revision: 0000000000000000000000000000000000000001\n"
        "    position: decisions/example.md#b\n",
    )
    # Duplicated file: 1 record repeats `default:` verbatim (+1), and 2 records share an identical synthetic
    # block (+1) -> total 2 repeated identical source blocks.
    _write(
        tmp_path / "examples" / "alpha" / "facts" / "dups.sources.yaml",
        "default:\n"
        "  kind: git\n"
        "  name: rezono-lang/rezono\n"
        "  revision: 0000000000000000000000000000000000000001\n"
        "  position: decisions/example.md\n"
        "records:\n"
        "  - of: {kind: item, id: r1}\n"
        "    kind: git\n"
        "    name: rezono-lang/rezono\n"
        "    revision: 0000000000000000000000000000000000000001\n"
        "    position: decisions/example.md\n"
        "  - of: {kind: item, id: r2}\n"
        "    kind: synthetic\n"
        "    name: decisions/example.md\n"
        "    position: block-1\n"
        "  - of: {kind: item, id: r3}\n"
        "    kind: synthetic\n"
        "    name: decisions/example.md\n"
        "    position: block-1\n",
    )

    counts = sb.count_duplicate_source_blocks(tmp_path)
    cell = "examples/alpha/facts/dups.sources.yaml"
    assert counts == {cell: 2}, counts

    # Evaluated via packs/std-budget: shrinking gives advisory slack; growth inside slack or above ceiling fails.
    shrunk = sb.evaluate_shortcut_budget(
        "duplicate_source_blocks",
        base_ceilings={cell: 2},
        head_ceilings={cell: 2},
        base_observed={cell: 2},
        head_observed={cell: 1},
    )
    assert shrunk["budget_raised"] == set()
    assert shrunk["budget_exceeded"] == set()
    assert shrunk["budget_ratchet_violation"] == set()
    assert ("duplicate_source_blocks", cell) in shrunk["budget_slack"]

    ratchet = sb.evaluate_shortcut_budget(
        "duplicate_source_blocks",
        base_ceilings={cell: 3},
        head_ceilings={cell: 3},
        base_observed={cell: 1},
        head_observed={cell: 2},
    )
    assert ("duplicate_source_blocks", cell) in ratchet["budget_ratchet_violation"]

    exceeded = sb.evaluate_shortcut_budget(
        "duplicate_source_blocks",
        base_ceilings={cell: 2},
        head_ceilings={cell: 2},
        base_observed={cell: 2},
        head_observed={cell: 3},
    )
    assert ("duplicate_source_blocks", cell) in exceeded["budget_exceeded"]
    assert ("duplicate_source_blocks", cell) in exceeded["budget_ratchet_violation"]

    raised = sb.evaluate_shortcut_budget(
        "duplicate_source_blocks",
        base_ceilings={cell: 2},
        head_ceilings={cell: 3, "examples/alpha/facts/clean.sources.yaml": 1},
        base_observed={cell: 2},
        head_observed={cell: 2, "examples/alpha/facts/clean.sources.yaml": 1},
    )
    assert ("duplicate_source_blocks", cell) in raised["budget_raised"]
    assert ("duplicate_source_blocks", "examples/alpha/facts/clean.sources.yaml") in raised["budget_raised"]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: Implement the monotonically shrinking "
           "`rezono_pack_dl_regression` budget in loop/shortcut_budgets.py and loop/shortcut-budget.json "
           "evaluated through packs/std-budget so packs with rezono/*.rezono can never add .dl files "
           "while .dl files in packs without a rezono/ module are visibly counted as off-board migration work. "
           "Waits for loop/tests/test_tooling_does_not_decide.py--test_monotonically_shrinking_budget_shared_form.",
)
def test_rezono_pack_dl_regression_budget_only_shrinks_and_counts_offboard(tmp_path: Path):
    sb, budget = _load_shortcut_budgets()
    assert "rezono_pack_dl_regression" in budget and isinstance(budget["rezono_pack_dl_regression"], dict)
    assert sb.check_shortcut_budget("rezono_pack_dl_regression", ROOT) == []

    # Three hand-worked packs:
    # 1. examples/hybrid: already has rezono/award.rezono + 2 .dl files -> regression budget cell = 2.
    # 2. examples/pure-rezono: has rezono/main.rezono + 0 .dl files -> absent from both maps.
    # 3. packs/legacy-dl: no rezono/ modules + 3 .dl files -> counted visibly in offboard_counts only.
    _write(tmp_path / "examples" / "hybrid" / "pack.yaml", "name: hybrid\nversion: 0.1.0\ndefault_language: en\n")
    _write(tmp_path / "examples" / "hybrid" / "rezono" / "award.rezono", "rezono 1\npack hybrid\n")
    _write(tmp_path / "examples" / "hybrid" / "rules" / "a.dl", ".decl a(x: symbol)\n")
    _write(tmp_path / "examples" / "hybrid" / "rules" / "b.dl", ".decl b(x: symbol)\n")

    _write(tmp_path / "examples" / "pure-rezono" / "pack.yaml", "name: pure-rezono\nversion: 0.1.0\ndefault_language: en\n")
    _write(tmp_path / "examples" / "pure-rezono" / "rezono" / "main.rezono", "rezono 1\npack pure-rezono\n")

    _write(tmp_path / "packs" / "legacy-dl" / "pack.yaml", "name: legacy-dl\nversion: 0.1.0\ndefault_language: en\n")
    for stem in ("x", "y", "z"):
        _write(tmp_path / "packs" / "legacy-dl" / "rules" / f"{stem}.dl", f".decl {stem}(v: symbol)\n")

    regression, offboard = sb.count_rezono_pack_dl_files(tmp_path)
    assert regression == {"examples/hybrid": 2}, regression
    assert offboard == {"packs/legacy-dl": 3}, offboard

    # Counter-case 1: adding a .dl file to an off-board pack without rezono/ is counted visibly, NOT blocked.
    _write(tmp_path / "packs" / "legacy-dl" / "rules" / "w.dl", ".decl w(v: symbol)\n")
    reg_after_offboard, off_after_offboard = sb.count_rezono_pack_dl_files(tmp_path)
    assert reg_after_offboard == {"examples/hybrid": 2}
    assert off_after_offboard == {"packs/legacy-dl": 4}
    verdict_offboard = sb.evaluate_shortcut_budget(
        "rezono_pack_dl_regression",
        base_ceilings={"examples/hybrid": 2},
        head_ceilings={"examples/hybrid": 2},
        base_observed=regression,
        head_observed=reg_after_offboard,
    )
    assert verdict_offboard["budget_raised"] == set()
    assert verdict_offboard["budget_exceeded"] == set()
    assert verdict_offboard["budget_ratchet_violation"] == set()

    # Counter-case 2: backsliding a pure-Rezono pack by adding a .dl file is refused immediately.
    _write(tmp_path / "examples" / "pure-rezono" / "rules" / "backslide.dl", ".decl s(v: symbol)\n")
    reg_backslide, _ = sb.count_rezono_pack_dl_files(tmp_path)
    assert reg_backslide == {"examples/hybrid": 2, "examples/pure-rezono": 1}
    verdict_backslide = sb.evaluate_shortcut_budget(
        "rezono_pack_dl_regression",
        base_ceilings={"examples/hybrid": 2},
        head_ceilings={"examples/hybrid": 2},
        base_observed=regression,
        head_observed=reg_backslide,
    )
    assert ("rezono_pack_dl_regression", "examples/pure-rezono") in verdict_backslide["budget_exceeded"]
    assert ("rezono_pack_dl_regression", "examples/pure-rezono") in verdict_backslide["budget_ratchet_violation"]

    # Counter-case 3: shrinking examples/hybrid from 2 -> 1 passes with advisory slack; regrowing inside slack fails.
    verdict_shrink = sb.evaluate_shortcut_budget(
        "rezono_pack_dl_regression",
        base_ceilings={"examples/hybrid": 2},
        head_ceilings={"examples/hybrid": 2},
        base_observed={"examples/hybrid": 2},
        head_observed={"examples/hybrid": 1},
    )
    assert verdict_shrink["budget_exceeded"] == set()
    assert verdict_shrink["budget_ratchet_violation"] == set()
    assert ("rezono_pack_dl_regression", "examples/hybrid") in verdict_shrink["budget_slack"]

    verdict_ratchet = sb.evaluate_shortcut_budget(
        "rezono_pack_dl_regression",
        base_ceilings={"examples/hybrid": 2},
        head_ceilings={"examples/hybrid": 2},
        base_observed={"examples/hybrid": 1},
        head_observed={"examples/hybrid": 2},
    )
    assert ("rezono_pack_dl_regression", "examples/hybrid") in verdict_ratchet["budget_ratchet_violation"]
