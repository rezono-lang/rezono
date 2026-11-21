"""Three monotonically shrinking shortcut budgets instantiated in the shared `packs/std-budget`
form (decisions/no-green-by-cheapest-route.md, decisions/tooling-does-not-decide.md §2.1):

1. `day_number_fields`: integer day-number schema fields (`*_day` or `YYYYMMDD` integer `day` slots)
   in pack schemas (native `date` slots are not counted).
2. `duplicate_source_blocks`: repeated identical source metadata blocks within a `.sources.yaml`
   sidecar file (comparing source blocks with `of` excluded across `default` and `records`).
3. `rezono_pack_dl_regression`: `.dl` files under `rules/` in any pack or example that already has
   at least one Rezono module (`rezono/**/*.rezono`), paired with visible off-board tracking of `.dl`
   files in packs that have not yet introduced a `rezono/` module.

Each test verifies:
- `evaluate_shortcut_budget` actually loads and evaluates `packs/std-budget` and fails closed when
  `packs/std-budget` is unavailable (forbidding any pure-Python bypass or fallback);
- `check_shortcut_budget` passes on the real repository tree AND fails on hand-worked counter-cases
  (ceiling excess and base-to-head within-slack ratchet growth, forbidding a trivial `return []` stub).
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

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


def _write_budget_json(root: Path, sections: dict[str, dict[str, int]]) -> None:
    full = {
        "day_number_fields": {},
        "duplicate_source_blocks": {},
        "rezono_pack_dl_regression": {},
        **sections,
    }
    _write(root / "loop" / "shortcut-budget.json", json.dumps(full, indent=2, sort_keys=True) + "\n")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, check=True, capture_output=True, text=True, encoding="utf-8"
    ).stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", "-A")
    _git(
        root,
        "-c", "user.name=test",
        "-c", "user.email=test@example.invalid",
        "-c", "commit.gpgsign=false",
        "commit", "-q", "--allow-empty", "-m", message,
    )
    return _git(root, "rev-parse", "HEAD")


def _clear_module_caches(module) -> None:
    for attr in dir(module):
        fn = getattr(module, attr, None)
        if callable(fn) and hasattr(fn, "cache_clear"):
            fn.cache_clear()


def _assert_uses_std_budget_fail_closed(sb, monkeypatch, budget_name: str, cell: str) -> None:
    """Prove `evaluate_shortcut_budget` loads and executes `packs/std-budget` and fails closed on pack error."""
    from rezono_compiler import pack as rezono_pack

    loaded_packs: list[Path] = []
    real_read = rezono_pack.read

    def spy_read(path, *args, **kwargs):
        loaded_packs.append(Path(path).resolve())
        return real_read(path, *args, **kwargs)

    _clear_module_caches(sb)
    monkeypatch.setattr(rezono_pack, "read", spy_read)
    sb.evaluate_shortcut_budget(
        budget_name,
        base_ceilings={cell: 1},
        head_ceilings={cell: 1},
        base_observed={cell: 1},
        head_observed={cell: 1},
    )
    assert STD_BUDGET.resolve() in loaded_packs, (
        f"evaluate_shortcut_budget must load packs/std-budget (no Python bypass), saw pack.read calls: {loaded_packs}"
    )

    # Fail closed: when packs/std-budget cannot be read, evaluate_shortcut_budget must raise rather than fall back.
    _clear_module_caches(sb)

    def broken_read(path, *args, **kwargs):
        if Path(path).resolve() == STD_BUDGET.resolve():
            raise rezono_pack.CompileError("simulated packs/std-budget failure")
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(rezono_pack, "read", broken_read)
    with pytest.raises((rezono_pack.CompileError, OSError, RuntimeError, ValueError)):
        sb.evaluate_shortcut_budget(
            budget_name,
            base_ceilings={cell: 1},
            head_ceilings={cell: 1},
            base_observed={cell: 1},
            head_observed={cell: 1},
        )
    monkeypatch.setattr(rezono_pack, "read", real_read)
    _clear_module_caches(sb)


def test_day_number_schema_fields_budget_only_shrinks(tmp_path: Path, monkeypatch):
    sb, budget = _load_shortcut_budgets()
    assert sb.BUDGET_PATH == "loop/shortcut-budget.json"
    assert "day_number_fields" in budget and isinstance(budget["day_number_fields"], dict)
    assert sb.check_shortcut_budget("day_number_fields", ROOT) == []
    _assert_uses_std_budget_fail_closed(sb, monkeypatch, "day_number_fields", "packs/p-legacy")

    # Hand-worked counter-case tree:
    # - packs/p-legacy has 2 integer day-number slots (`valid_from_day`, `day` YYYYMMDD) plus 2 native date
    #   slots (`valid_from: date`, `cal: CalendarDate`) that must NOT be counted.
    # - examples/p-rezono has 1 integer day-number slot (`issued_on_day: Int`) plus 1 native `Date` slot.
    tree = tmp_path / "tree"
    _write(
        tree / "packs" / "p-legacy" / "pack.yaml",
        "name: p-legacy\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tree / "packs" / "p-legacy" / "schema" / "dates.yaml",
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
        tree / "examples" / "p-rezono" / "pack.yaml",
        "name: p-rezono\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tree / "examples" / "p-rezono" / "rezono" / "model.rezono",
        "rezono 1\npack p-rezono\n\nkind Note\n  issued_on: Date\n  issued_on_day: Int\n",
    )

    counts = sb.count_day_number_fields(tree)
    assert counts == {"examples/p-rezono": 1, "packs/p-legacy": 2}, counts

    # Negative counter-case on check_shortcut_budget (refuses ceiling excess; catches a `return []` stub).
    _write_budget_json(tree, {"day_number_fields": {"examples/p-rezono": 1, "packs/p-legacy": 1}})
    excess_findings = sb.check_shortcut_budget("day_number_fields", tree)
    assert excess_findings, "check_shortcut_budget must fail when observed count exceeds ceiling"
    assert any("packs/p-legacy" in msg for msg in excess_findings), excess_findings

    # Negative base-to-head ratchet counter-case on check_shortcut_budget (growth inside slack fails).
    repo = tmp_path / "git-ratchet"
    _write(repo / "packs" / "p-legacy" / "pack.yaml", "name: p-legacy\nversion: 0.1.0\ndefault_language: en\n")
    _write(
        repo / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\nname: p_legacy\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      valid_from_day: {range: integer}\n",
    )
    _write_budget_json(repo, {"day_number_fields": {"packs/p-legacy": 2}})
    _git(repo, "init", "-q")
    base_sha = _commit(repo, "base with 1 day-number field and ceiling 2")
    _write(
        repo / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\nname: p_legacy\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      valid_from_day: {range: integer}\n      valid_until_day: {range: integer}\n",
    )
    _commit(repo, "head grows observed count inside slack from 1 to 2")
    ratchet_findings = sb.check_shortcut_budget("day_number_fields", repo, base=base_sha)
    assert ratchet_findings, "check_shortcut_budget must fail on base-to-head growth inside slack"
    assert any("packs/p-legacy" in msg for msg in ratchet_findings), ratchet_findings

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

    ratchet = sb.evaluate_shortcut_budget(
        "day_number_fields",
        base_ceilings={"packs/p-legacy": 2},
        head_ceilings={"packs/p-legacy": 2},
        base_observed={"packs/p-legacy": 1},
        head_observed={"packs/p-legacy": 2},
    )
    assert ("day_number_fields", "packs/p-legacy") in ratchet["budget_ratchet_violation"]

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


def test_duplicate_source_blocks_budget_only_shrinks(tmp_path: Path, monkeypatch):
    sb, budget = _load_shortcut_budgets()
    assert "duplicate_source_blocks" in budget and isinstance(budget["duplicate_source_blocks"], dict)
    assert sb.check_shortcut_budget("duplicate_source_blocks", ROOT) == []
    cell = "examples/alpha/facts/dups.sources.yaml"
    _assert_uses_std_budget_fail_closed(sb, monkeypatch, "duplicate_source_blocks", cell)

    tree = tmp_path / "tree"
    # Clean file: shared block once in `default:`, distinct record positions -> 0 duplicates.
    _write(
        tree / "examples" / "alpha" / "facts" / "clean.sources.yaml",
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
    dups_text = (
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
        "    position: block-1\n"
    )
    _write(tree / cell, dups_text)

    counts = sb.count_duplicate_source_blocks(tree)
    assert counts == {cell: 2}, counts

    # Negative counter-case on check_shortcut_budget (ceiling excess fails; catches a `return []` stub).
    _write_budget_json(tree, {"duplicate_source_blocks": {cell: 1}})
    excess_findings = sb.check_shortcut_budget("duplicate_source_blocks", tree)
    assert excess_findings, "check_shortcut_budget must fail when duplicate source blocks exceed ceiling"
    assert any(cell in msg for msg in excess_findings), excess_findings

    # Negative base-to-head ratchet counter-case on check_shortcut_budget (growth inside slack fails).
    repo = tmp_path / "git-ratchet"
    _write(
        repo / cell,
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
        "    position: decisions/example.md\n",
    )
    _write_budget_json(repo, {"duplicate_source_blocks": {cell: 3}})
    _git(repo, "init", "-q")
    base_sha = _commit(repo, "base with 1 duplicate and ceiling 3")
    _write(repo / cell, dups_text)
    _commit(repo, "head grows duplicates inside slack from 1 to 2")
    ratchet_findings = sb.check_shortcut_budget("duplicate_source_blocks", repo, base=base_sha)
    assert ratchet_findings, "check_shortcut_budget must fail on base-to-head duplicate growth inside slack"
    assert any(cell in msg for msg in ratchet_findings), ratchet_findings

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


def test_rezono_pack_dl_regression_budget_only_shrinks_and_counts_offboard(tmp_path: Path, monkeypatch):
    sb, budget = _load_shortcut_budgets()
    assert "rezono_pack_dl_regression" in budget and isinstance(budget["rezono_pack_dl_regression"], dict)
    assert sb.check_shortcut_budget("rezono_pack_dl_regression", ROOT) == []
    _assert_uses_std_budget_fail_closed(sb, monkeypatch, "rezono_pack_dl_regression", "examples/hybrid")

    # Three hand-worked packs:
    # 1. examples/hybrid: already has rezono/award.rezono + 2 .dl files -> regression budget cell = 2.
    # 2. examples/pure-rezono: has rezono/main.rezono + 0 .dl files -> absent from both maps.
    # 3. packs/legacy-dl: no rezono/ modules + 3 .dl files -> counted visibly in offboard_counts only.
    tree = tmp_path / "tree"
    _write(tree / "examples" / "hybrid" / "pack.yaml", "name: hybrid\nversion: 0.1.0\ndefault_language: en\n")
    _write(tree / "examples" / "hybrid" / "rezono" / "award.rezono", "rezono 1\npack hybrid\n")
    _write(tree / "examples" / "hybrid" / "rules" / "a.dl", ".decl a(x: symbol)\n")
    _write(tree / "examples" / "hybrid" / "rules" / "b.dl", ".decl b(x: symbol)\n")

    _write(tree / "examples" / "pure-rezono" / "pack.yaml", "name: pure-rezono\nversion: 0.1.0\ndefault_language: en\n")
    _write(tree / "examples" / "pure-rezono" / "rezono" / "main.rezono", "rezono 1\npack pure-rezono\n")

    _write(tree / "packs" / "legacy-dl" / "pack.yaml", "name: legacy-dl\nversion: 0.1.0\ndefault_language: en\n")
    for stem in ("x", "y", "z"):
        _write(tree / "packs" / "legacy-dl" / "rules" / f"{stem}.dl", f".decl {stem}(v: symbol)\n")

    regression, offboard = sb.count_rezono_pack_dl_files(tree)
    assert regression == {"examples/hybrid": 2}, regression
    assert offboard == {"packs/legacy-dl": 3}, offboard

    # Counter-case 1: adding a .dl file to an off-board pack without rezono/ is counted visibly, NOT blocked.
    _write(tree / "packs" / "legacy-dl" / "rules" / "w.dl", ".decl w(v: symbol)\n")
    reg_after_offboard, off_after_offboard = sb.count_rezono_pack_dl_files(tree)
    assert reg_after_offboard == {"examples/hybrid": 2}
    assert off_after_offboard == {"packs/legacy-dl": 4}
    _write_budget_json(tree, {"rezono_pack_dl_regression": {"examples/hybrid": 2}})
    assert sb.check_shortcut_budget("rezono_pack_dl_regression", tree) == []

    # Counter-case 2: backsliding a pure-Rezono pack by adding a .dl file is refused by check_shortcut_budget.
    _write(tree / "examples" / "pure-rezono" / "rules" / "backslide.dl", ".decl s(v: symbol)\n")
    reg_backslide, _ = sb.count_rezono_pack_dl_files(tree)
    assert reg_backslide == {"examples/hybrid": 2, "examples/pure-rezono": 1}
    backslide_findings = sb.check_shortcut_budget("rezono_pack_dl_regression", tree)
    assert backslide_findings, "check_shortcut_budget must refuse a new .dl file in a pure-Rezono pack"
    assert any("examples/pure-rezono" in msg for msg in backslide_findings), backslide_findings

    verdict_backslide = sb.evaluate_shortcut_budget(
        "rezono_pack_dl_regression",
        base_ceilings={"examples/hybrid": 2},
        head_ceilings={"examples/hybrid": 2},
        base_observed=regression,
        head_observed=reg_backslide,
    )
    assert ("rezono_pack_dl_regression", "examples/pure-rezono") in verdict_backslide["budget_exceeded"]
    assert ("rezono_pack_dl_regression", "examples/pure-rezono") in verdict_backslide["budget_ratchet_violation"]

    # Counter-case 3: base-to-head ratchet violation inside slack fails check_shortcut_budget.
    repo = tmp_path / "git-ratchet"
    _write(repo / "examples" / "hybrid" / "pack.yaml", "name: hybrid\nversion: 0.1.0\ndefault_language: en\n")
    _write(repo / "examples" / "hybrid" / "rezono" / "award.rezono", "rezono 1\npack hybrid\n")
    _write(repo / "examples" / "hybrid" / "rules" / "a.dl", ".decl a(x: symbol)\n")
    _write_budget_json(repo, {"rezono_pack_dl_regression": {"examples/hybrid": 2}})
    _git(repo, "init", "-q")
    base_sha = _commit(repo, "base with 1 .dl file and ceiling 2")
    _write(repo / "examples" / "hybrid" / "rules" / "b.dl", ".decl b(x: symbol)\n")
    _commit(repo, "head adds a second .dl file inside slack")
    ratchet_findings = sb.check_shortcut_budget("rezono_pack_dl_regression", repo, base=base_sha)
    assert ratchet_findings, "check_shortcut_budget must fail on base-to-head .dl growth inside slack"
    assert any("examples/hybrid" in msg for msg in ratchet_findings), ratchet_findings

    # Counter-case 4: shrinking examples/hybrid from 2 -> 1 passes with advisory slack; regrowing inside slack fails.
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
