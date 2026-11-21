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

import ast
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
PACKS = ROOT / "packs"
STD_BUDGET = PACKS / "std-budget"
BUDGET_FILE = ROOT / "loop" / "shortcut-budget.json"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SHORTCUT_BUDGETS_PY = ROOT / "loop" / "shortcut_budgets.py"


def _repo_base() -> str:
    """Base git revision for repository-wide budget checks (CI PR/merge-queue base, else HEAD)."""
    raw = (os.environ.get("SHORTCUT_BUDGET_BASE") or os.environ.get("DECISION_HEADS_BASE") or "").strip()
    if raw and not set(raw) <= {"0"}:
        return raw
    return "HEAD"


def _load_shortcut_budgets():
    assert (STD_BUDGET / "pack.yaml").is_file(), "packs/std-budget does not exist yet"
    assert BUDGET_FILE.is_file(), "loop/shortcut-budget.json does not exist yet"
    raw = BUDGET_FILE.read_text(encoding="utf-8")
    parsed = json.loads(raw)
    assert raw == json.dumps(parsed, indent=2, sort_keys=True) + "\n", (
        "loop/shortcut-budget.json must be canonical sorted JSON with 2-space indent and trailing LF"
    )
    try:
        from loop import shortcut_budgets
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
    assert sb.check_shortcut_budget("day_number_fields", ROOT, base=_repo_base()) == []
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
    _git(tree, "init", "-q")
    tree_base = _commit(tree, "base with ceiling excess")
    excess_findings = sb.check_shortcut_budget("day_number_fields", tree, base=tree_base)
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
    assert sb.check_shortcut_budget("duplicate_source_blocks", ROOT, base=_repo_base()) == []
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
    _git(tree, "init", "-q")
    tree_base = _commit(tree, "base with duplicate excess")
    excess_findings = sb.check_shortcut_budget("duplicate_source_blocks", tree, base=tree_base)
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
    assert sb.check_shortcut_budget("rezono_pack_dl_regression", ROOT, base=_repo_base()) == []
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
    _git(tree, "init", "-q")
    tree_base = _commit(tree, "base with hybrid=2 and offboard=4")
    assert sb.check_shortcut_budget("rezono_pack_dl_regression", tree, base=tree_base) == []

    # Counter-case 2: backsliding a pure-Rezono pack by adding a .dl file is refused by check_shortcut_budget.
    _write(tree / "examples" / "pure-rezono" / "rules" / "backslide.dl", ".decl s(v: symbol)\n")
    reg_backslide, _ = sb.count_rezono_pack_dl_files(tree)
    assert reg_backslide == {"examples/hybrid": 2, "examples/pure-rezono": 1}
    backslide_findings = sb.check_shortcut_budget("rezono_pack_dl_regression", tree, base=tree_base)
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


def _find_bash() -> str:
    if os.name == "nt":
        git_exe = shutil.which("git")
        if git_exe:
            git_bash = Path(git_exe).resolve().parents[1] / "bin" / "bash.exe"
            if git_bash.is_file():
                return str(git_bash)
    bash = shutil.which("bash")
    assert bash, "bash executable not found on PATH"
    return bash


def _python_bin_for_ci_step(tmp_path: Path) -> tuple[str, dict[str, str]]:
    """Return `(bin_dir, extra_env)` so `python -I` in ci.yml finds `yaml` and `rezono_compiler`.

    In CI (or any editable venv) `sys.executable -I` already resolves both packages and is used
    directly; only when running locally via `PYTHONPATH`/user-site does a small test shim forward
    to `sys.executable` with the current `sys.path`.
    """
    probe = subprocess.run(
        [sys.executable, "-I", "-c", "import yaml, rezono_compiler"],
        capture_output=True,
    )
    if probe.returncode == 0:
        return str(Path(sys.executable).parent), {}
    shim_dir = tmp_path / "python-shim"
    shim_dir.mkdir()
    exe_posix = Path(sys.executable).as_posix()
    shim = shim_dir / "python"
    shim.write_text(
        "#!/usr/bin/env bash\n"
        'if [[ "${1:-}" == "-I" ]]; then shift; fi\n'
        f'exec "{exe_posix}" "$@"\n',
        encoding="utf-8",
        newline="\n",
    )
    shim.chmod(0o755)
    return str(shim_dir), {"PYTHONPATH": os.pathsep.join(p for p in sys.path if p)}


WEAKENED_STD_BUDGET_DL = """// Weakened candidate std-budget stub that compiles cleanly yet never blocks any cell.
.decl budget_ceiling(budget: symbol, cell: symbol, revision: symbol, ceiling: number)
budget_ceiling(b, c, r, n) :- budget_entry(e), budget_entry__budget(e, b), budget_entry__cell(e, c),
    budget_entry__revision(e, r), budget_entry__ceiling(e, n).
.decl budget_observed(budget: symbol, cell: symbol, revision: symbol, observed: number)
budget_observed(b, c, r, n) :- budget_reading(x), budget_reading__budget(x, b), budget_reading__cell(x, c),
    budget_reading__revision(x, r), budget_reading__observed(x, n).
.decl has_base_ceiling(budget: symbol, cell: symbol)
has_base_ceiling(b, c) :- budget_ceiling(b, c, "base", _).
.decl has_head_ceiling(budget: symbol, cell: symbol)
has_head_ceiling(b, c) :- budget_ceiling(b, c, "head", _).
.decl has_base_observed(budget: symbol, cell: symbol)
has_base_observed(b, c) :- budget_observed(b, c, "base", _).
.decl has_head_observed(budget: symbol, cell: symbol)
has_head_observed(b, c) :- budget_observed(b, c, "head", _).
.decl budget_cell(budget: symbol, cell: symbol)
budget_cell(b, c) :- budget_ceiling(b, c, _, _).
budget_cell(b, c) :- budget_observed(b, c, _, _).
.decl budget_raised(budget: symbol, cell: symbol)
budget_raised(b, c) :- budget_cell(b, c), b = "__never__".
.decl budget_exceeded(budget: symbol, cell: symbol)
budget_exceeded(b, c) :- budget_cell(b, c), b = "__never__".
.decl budget_ratchet_violation(budget: symbol, cell: symbol)
budget_ratchet_violation(b, c) :- budget_cell(b, c), b = "__never__".
.decl budget_missing_head(budget: symbol, cell: symbol)
budget_missing_head(b, c) :- budget_cell(b, c), b = "__never__".
.decl budget_slack(budget: symbol, cell: symbol)
budget_slack(b, c) :- budget_cell(b, c), b = "__never__".
.decl budget_within(budget: symbol, cell: symbol)
budget_within(b, c) :- budget_cell(b, c).
.output budget_raised, budget_exceeded, budget_ratchet_violation, budget_missing_head, budget_slack, budget_within
"""


def test_ci_workflow_runs_base_shortcut_budgets_with_base_revision(tmp_path: Path):
    """CI executes the base revision's loop/shortcut_budgets.py AND packs/std-budget with --base on PRs and merge_group."""
    workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
    discover_steps = workflow["jobs"]["discover"]["steps"]
    env_index, = [
        i for i, step in enumerate(discover_steps)
        if step.get("uses") == "./.github/workflows/python-environment"
    ]
    budget_steps = [
        (i, step)
        for i, step in enumerate(discover_steps)
        if "shortcut_budgets.py" in (step.get("run") or "")
    ]
    assert len(budget_steps) == 1, f"expected one shortcut budget gate step in ci.yml discover, got {budget_steps}"
    idx, step = budget_steps[0]
    assert env_index < idx, "shortcut budget gate must run after python-environment installs rezono_compiler"
    assert not step.get("continue-on-error"), "shortcut budget gate must block CI, never continue-on-error"
    assert "if" not in step, "shortcut budget gate must run on every PR, merge_group and push that discover runs"

    env = step.get("env") or {}
    policy_expr = str(env.get("POLICY") or "")
    base_expr = str(env.get("BASE") or "")
    for required_ref in ("github.event.pull_request.base.sha", "github.event.merge_group.base_sha"):
        assert required_ref in policy_expr, f"POLICY env must cover {required_ref}: {policy_expr!r}"
        assert required_ref in base_expr, f"BASE env must cover {required_ref}: {base_expr!r}"
    assert "github.sha" in policy_expr, f"POLICY env must fall back to github.sha: {policy_expr!r}"
    assert "github.event.before" in base_expr, f"BASE env must cover push github.event.before: {base_expr!r}"

    python_steps = workflow["jobs"]["python"]["steps"]
    check_step, = [s for s in python_steps if "components.py run-shard" in (s.get("run") or "")]
    sb_base_expr = str((check_step.get("env") or {}).get("SHORTCUT_BUDGET_BASE") or "")
    assert "github.event.pull_request.base.sha" in sb_base_expr, sb_base_expr
    assert "github.event.merge_group.base_sha" in sb_base_expr, sb_base_expr

    # Execute the actual ci.yml step script against a temporary fixture repository.
    run_script = step["run"]
    repo = tmp_path / "ci-shortcut-budget-repo"
    (repo / "loop").mkdir(parents=True)
    shutil.copy2(SHORTCUT_BUDGETS_PY, repo / "loop" / "shortcut_budgets.py")
    shutil.copytree(STD_BUDGET, repo / "packs" / "std-budget")
    _write(repo / "packs" / "p-legacy" / "pack.yaml", "name: p-legacy\nversion: 0.1.0\ndefault_language: en\n")
    _write(
        repo / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\nname: p_legacy\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      valid_from_day: {range: integer}\n",
    )
    _write_budget_json(repo, {"day_number_fields": {"packs/p-legacy": 1}})
    _git(repo, "init", "-q")
    _git(repo, "config", "core.autocrlf", "false")
    base_sha = _commit(repo, "base with real shortcut_budgets.py and packs/std-budget")

    bash = _find_bash()
    python_bin_dir, extra_env = _python_bin_for_ci_step(tmp_path)
    step_env = {
        **os.environ,
        **extra_env,
        "PATH": python_bin_dir + os.pathsep + os.environ.get("PATH", ""),
        "POLICY": base_sha,
        "BASE": base_sha,
    }

    # 1. Clean candidate matching base passes and cleans up .shortcut-budget-base.
    clean = subprocess.run([bash, "-c", run_script], cwd=repo, env=step_env, capture_output=True, text=True, encoding="utf-8")
    assert clean.returncode == 0, f"CI step failed on clean fixture repo:\n{clean.stdout}\n{clean.stderr}"
    assert not (repo / ".shortcut-budget-base").exists(), "CI step did not clean up .shortcut-budget-base"

    # 2. Candidate grows day_number_fields, raises its ceiling, AND weakens packs/std-budget
    #    (renaming pack.yaml away from the reserved standard name so compiler hash pinning alone
    #    would not block a weakened candidate pack).
    _write(
        repo / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\nname: p_legacy\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      valid_from_day: {range: integer}\n      valid_until_day: {range: integer}\n",
    )
    _write_budget_json(repo, {"day_number_fields": {"packs/p-legacy": 2}})
    _write(
        repo / "packs" / "std-budget" / "pack.yaml",
        "name: weakened-budget\nversion: 0.1.0\ndefault_language: en\nimports: []\n",
    )
    _write(repo / "packs" / "std-budget" / "rules" / "budget.dl", WEAKENED_STD_BUDGET_DL)

    # Positive control: running directly against the candidate's weakened packs/std-budget would silently pass.
    control_cmd = [sys.executable, str(repo / "loop" / "shortcut_budgets.py"), "--root", str(repo), "--base", base_sha]
    if not extra_env:
        control_cmd.insert(1, "-I")
    control = subprocess.run(
        control_cmd,
        cwd=repo,
        env={**os.environ, **extra_env},
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert control.returncode == 0, (
        f"positive control expected weakened candidate packs/std-budget to pass locally, got rc={control.returncode}: "
        f"{control.stdout}\n{control.stderr}"
    )

    # Actual CI step must fail because it evaluates packs/std-budget from $POLICY, not from the candidate tree.
    weakened_pack = subprocess.run(
        [bash, "-c", run_script],
        cwd=repo,
        env=step_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert weakened_pack.returncode != 0, (
        f"weakened candidate packs/std-budget bypassed the CI step!\nstdout:\n{weakened_pack.stdout}\nstderr:\n{weakened_pack.stderr}"
    )
    assert "budget_raised" in weakened_pack.stdout, weakened_pack.stdout
    assert "budget_ratchet_violation" in weakened_pack.stdout, weakened_pack.stdout
    assert not (repo / ".shortcut-budget-base").exists(), "CI step did not clean up .shortcut-budget-base on failure"

    # 3. Candidate also weakens loop/shortcut_budgets.py to exit 0; CI step still fails from $POLICY.
    _write(repo / "loop" / "shortcut_budgets.py", "raise SystemExit(0)\n")
    weakened_script = subprocess.run(
        [bash, "-c", run_script],
        cwd=repo,
        env=step_env,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert weakened_script.returncode != 0, (
        f"weakened candidate loop/shortcut_budgets.py bypassed the CI step!\nstdout:\n{weakened_script.stdout}\nstderr:\n{weakened_script.stderr}"
    )
    assert "budget_raised" in weakened_script.stdout, weakened_script.stdout
    assert "budget_ratchet_violation" in weakened_script.stdout, weakened_script.stdout


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: loop/shortcut_budgets.py must refuse missing or "
           "empty --base instead of silently equating head to base, and fail closed when any ceiling in "
           "loop/shortcut-budget.json is raised or added relative to --base.",
)
def test_shortcut_budgets_refuses_missing_base_and_detects_raised_ceiling(tmp_path: Path, capsys):
    sb, _ = _load_shortcut_budgets()
    repo = tmp_path / "budget-raised-repo"
    _write(repo / "packs" / "p-legacy" / "pack.yaml", "name: p-legacy\nversion: 0.1.0\ndefault_language: en\n")
    _write(
        repo / "packs" / "p-legacy" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-legacy\nname: p_legacy\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      valid_from_day: {range: integer}\n",
    )
    _write_budget_json(repo, {"day_number_fields": {"packs/p-legacy": 1}})
    _git(repo, "init", "-q")
    base_sha = _commit(repo, "base with ceiling 1")

    # Raise existing ceiling (1 -> 2) and add a new cell (examples/p-new: 1) while keeping observed counts
    # inside the raised ceilings, so only base-to-head ceiling comparison catches the regression.
    _write(repo / "examples" / "p-new" / "pack.yaml", "name: p-new\nversion: 0.1.0\ndefault_language: en\n")
    _write(
        repo / "examples" / "p-new" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-new\nname: p_new\nclasses:\n  Item:\n    attributes:\n"
        "      id: {identifier: true}\n      start_day: {range: integer}\n",
    )
    _write_budget_json(repo, {"day_number_fields": {"examples/p-new": 1, "packs/p-legacy": 2}})
    _commit(repo, "head raises packs/p-legacy ceiling and adds examples/p-new")

    # 1. Explicit --base must detect both raised ceilings via API and CLI.
    findings = sb.check_shortcut_budget("day_number_fields", repo, base=base_sha)
    assert any("budget_raised" in msg and "packs/p-legacy" in msg for msg in findings), findings
    assert any("budget_raised" in msg and "examples/p-new" in msg for msg in findings), findings

    rc_with_base = sb.main(["--root", str(repo), "--base", base_sha, "--budget", "day_number_fields"])
    captured = capsys.readouterr()
    assert rc_with_base != 0, f"CLI with --base must fail on raised ceiling, got rc={rc_with_base}"
    assert "budget_raised" in captured.out, captured.out

    # 2. Missing or empty base in check_shortcut_budget must fail closed (never silently equate base to head).
    for label, call in (
        ("omitted base", lambda: sb.check_shortcut_budget("day_number_fields", repo)),
        ("base=None", lambda: sb.check_shortcut_budget("day_number_fields", repo, base=None)),
        ("empty base", lambda: sb.check_shortcut_budget("day_number_fields", repo, base="")),
        ("whitespace base", lambda: sb.check_shortcut_budget("day_number_fields", repo, base="   ")),
    ):
        try:
            outcome = call()
        except (TypeError, ValueError):
            continue
        raise AssertionError(
            f"check_shortcut_budget with {label} must fail closed (TypeError/ValueError), "
            f"not silently treat head as base; got {outcome!r}"
        )

    # 3. Missing or empty --base in CLI main() must fail closed (never exit 0).
    for label, argv in (
        ("missing --base", ["--root", str(repo), "--budget", "day_number_fields"]),
        ("empty --base", ["--root", str(repo), "--base", "", "--budget", "day_number_fields"]),
    ):
        try:
            rc = sb.main(argv)
        except SystemExit as exc:
            assert exc.code not in (0, None), f"CLI {label} exited cleanly with {exc.code!r}"
            continue
        assert rc != 0, f"CLI {label} must fail closed (non-zero exit), not silently treat head as base"


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/no-green-by-cheapest-route.md: loop/shortcut_budgets.py must count "
           "day_number_fields from the rezono_compiler schema/module model (resolving LinkML and Rezono "
           "scalar type aliases) instead of bespoke regex scanning over .rezono source text.",
)
def test_day_number_field_counter_uses_compiler_model_not_regex(tmp_path: Path):
    sb, _ = _load_shortcut_budgets()

    # 1. Structural AST check: forbid regex-based parsing of .rezono declarations/slots in loop/shortcut_budgets.py.
    source = SHORTCUT_BUDGETS_PY.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(SHORTCUT_BUDGETS_PY))
    regex_funcs = {"compile", "match", "search", "fullmatch", "findall", "finditer", "sub"}
    regex_patterns = [
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in regex_funcs
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    rezono_regexes = [
        pat
        for pat in regex_patterns
        if any(token in pat for token in ("kind", "extend", "derived", r"\s*:"))
    ]
    assert not rezono_regexes, (
        f"loop/shortcut_budgets.py must not parse .rezono declarations with regexes: {rezono_regexes}"
    )

    # Confirm the day-number counting path imports rezono_compiler (not only evaluate_shortcut_budget).
    non_eval_compiler_imports = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_shortcut_budget":
            continue
        if isinstance(node, ast.FunctionDef) and any(
            isinstance(sub, ast.Constant) and isinstance(sub.value, str) and "std-budget" in sub.value
            for sub in ast.walk(node)
        ):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and (sub.module or "").startswith("rezono_compiler"):
                non_eval_compiler_imports.append(sub.module)
            elif isinstance(sub, ast.Import) and any(a.name.startswith("rezono_compiler") for a in sub.names):
                non_eval_compiler_imports.extend(a.name for a in sub.names if a.name.startswith("rezono_compiler"))
    assert non_eval_compiler_imports, (
        "loop/shortcut_budgets.py must read pack schemas/modules via rezono_compiler in its day-number counter"
    )

    # 2. Behavioral semantic check: scalar type aliases in both LinkML YAML and Rezono modules resolve
    #    through the compiler/schema model (a raw-dict/regex name check misses aliased integer types).
    tree_dir = tmp_path / "alias-tree"
    _write(
        tree_dir / "packs" / "p-yaml-alias" / "pack.yaml",
        "name: p-yaml-alias\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tree_dir / "packs" / "p-yaml-alias" / "schema" / "dates.yaml",
        "id: https://rezono.org/test/p-yaml-alias\n"
        "name: p_yaml_alias\n"
        "imports: [linkml:types]\n"
        "types:\n"
        "  DayStamp:\n"
        "    typeof: integer\n"
        "  DayLabel:\n"
        "    typeof: string\n"
        "classes:\n"
        "  Item:\n"
        "    attributes:\n"
        "      id: {identifier: true}\n"
        "      effective_day: {range: DayStamp}\n"
        "      label_day: {range: DayLabel}\n"
        "      recorded_on: {range: date}\n",
    )
    _write(
        tree_dir / "examples" / "p-rezono-alias" / "pack.yaml",
        "name: p-rezono-alias\nversion: 0.1.0\ndefault_language: en\n",
    )
    _write(
        tree_dir / "examples" / "p-rezono-alias" / "rezono" / "model.rezono",
        "rezono 1\n"
        "pack p-rezono-alias\n\n"
        "type DayStamp = Int\n"
        "type DayLabel = Text\n\n"
        "kind Entry world closed\n"
        "  id: Text identifier\n"
        "  effective_day: DayStamp\n"
        "  label_day: DayLabel\n"
        "  recorded_on: Date\n",
    )

    counts = sb.count_day_number_fields(tree_dir)
    assert counts == {"examples/p-rezono-alias": 1, "packs/p-yaml-alias": 1}, (
        f"day-number counter must resolve integer type aliases through rezono_compiler, got {counts}"
    )
