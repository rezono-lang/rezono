"""No duplicate Python calculators beside pack rules or shared readers (decisions/code-does-not-decide.md).

Verifies that:
1. `loop/build_cutover.py` does not reimplement `loop/build_selection_outcome.py` with a divergent
   manifest-acceptance rule (single shared strict acceptance decision, or duplicate retired).
2. `loop/status_times.py` and `loop/flow_evidence.py` do not remain in production `loop/` computing
   live delivery-time or flow-witness decisions beside the `std-loop` pack rules.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
LOOP = ROOT / "loop"
STD_LOOP = ROOT / "packs" / "std-loop"

UNIVERSE = ("alpha", "beta", "gamma")
GREEN_BOTH = {
    "checks": [
        {"name": "rezono:proofs", "status": "green"},
        {"name": "rezono:schema", "status": "green"},
    ]
}


def _rows(*keys: tuple[str, ...]) -> list[dict[str, list[str]]]:
    return [{"key": list(key)} for key in keys]


def _imported_local_modules(path: Path) -> set[str]:
    """Return local module stems imported by `path` via AST."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
                found.add(alias.name.rpartition(".")[2])
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            if mod:
                found.add(mod)
                found.add(mod.rpartition(".")[2])
            for alias in node.names:
                if mod in {"", "loop"}:
                    found.add(alias.name)
    return found


def _production_loop_python_files() -> list[Path]:
    """All non-test Python files under `loop/`."""
    out: list[Path] = []
    for path in sorted(LOOP.rglob("*.py")):
        rel_parts = path.relative_to(LOOP).parts
        if "tests" in rel_parts or "fixtures" in rel_parts:
            continue
        if path.name.startswith("test_") or path.name.endswith("_test.py"):
            continue
        out.append(path)
    return out


def _references_module_dynamically(path: Path, stem: str) -> bool:
    """Detect dynamic loads (`run_path`, `import_module`, `find_spec`) targeting `stem`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    dynamic_loaders = {"run_path", "import_module", "find_spec", "spec_from_file_location"}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        callee = (
            node.func.id
            if isinstance(node.func, ast.Name)
            else node.func.attr
            if isinstance(node.func, ast.Attribute)
            else ""
        )
        if callee not in dynamic_loaders:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Constant) and isinstance(sub.value, str):
                if stem in sub.value:
                    return True
    return False


def test_build_cutover_and_selection_outcome_share_one_strict_acceptance_rule():
    from loop.build_cutover import select_suites

    cutover_path = LOOP / "build_cutover.py"
    outcome_path = LOOP / "build_selection_outcome.py"
    assert cutover_path.is_file(), "loop/build_cutover.py is missing"

    selected = {
        "build_selected_job": _rows(("r1", "beta", "change"), ("r1", "alpha", "change")),
        "build_full_selection": [],
    }
    full_selected = {
        "build_selected_job": selected["build_selected_job"],
        "build_full_selection": _rows(("r1", "unmapped.txt")),
    }
    cases = (
        ("both-green", GREEN_BOTH, selected, None, True, None),
        ("full-selection-row", GREEN_BOTH, full_selected, None, True, None),
        (
            "missing-proofs",
            {"checks": [{"name": "rezono:schema", "status": "green"}]},
            selected,
            None,
            False,
            "invalid-publication",
        ),
        (
            "missing-schema",
            {"checks": [{"name": "rezono:proofs", "status": "green"}]},
            selected,
            None,
            False,
            "invalid-publication",
        ),
        (
            "unrelated-green-check",
            {"checks": [{"name": "custom:only", "status": "green"}]},
            selected,
            None,
            False,
            "invalid-publication",
        ),
        (
            "red-proofs",
            {
                "checks": [
                    {"name": "rezono:proofs", "status": "red"},
                    {"name": "rezono:schema", "status": "green"},
                ]
            },
            selected,
            None,
            False,
            "invalid-publication",
        ),
        ("empty-checks", {"checks": []}, selected, None, False, "invalid-publication"),
        (
            "missing-relation",
            GREEN_BOTH,
            {"build_selected_job": selected["build_selected_job"]},
            None,
            False,
            "invalid-publication",
        ),
        ("missing-publication", None, None, None, False, "missing-publication"),
        ("engine-failure", GREEN_BOTH, selected, "compile failed", False, "engine-failure"),
    )

    # Strict acceptance invariant on loop/build_cutover.py across all cases.
    for label, manifest, rows, err, expect_accepted, expected_reason in cases:
        got = select_suites(
            run="r1",
            manifest=manifest,
            rows=rows,
            engine_error=err,
            universe=UNIVERSE,
        )
        if expect_accepted:
            assert got["source"] == "pack" and got["safe_mode"] is False, (label, got)
        else:
            assert got["source"] == "safe_mode" and got["safe_mode"] is True, (label, got)
            assert got["safe_mode_reason"] == expected_reason, (label, got)
            assert got["use"] == sorted(UNIVERSE), (label, got)

    # If loop/build_selection_outcome.py still exists alongside loop/build_cutover.py,
    # both must enforce the exact same strict acceptance rule and share one implementation.
    if outcome_path.is_file():
        from loop.build_selection_outcome import selection_outcome

        for label, manifest, rows, err, expect_accepted, expected_reason in cases:
            outcome = selection_outcome(run="r1", manifest=manifest, rows=rows, engine_error=err)
            if not expect_accepted:
                assert outcome == {
                    "mode": "full",
                    "suites": [],
                    "reasons": [expected_reason],
                }, (
                    f"{label}: loop/build_selection_outcome.py diverged from loop/build_cutover.py "
                    f"(expected invalid/full with {expected_reason!r}, got {outcome!r})"
                )
            elif label == "both-green":
                assert outcome == {"mode": "selected", "suites": ["alpha", "beta"], "reasons": []}, (label, outcome)
            elif label == "full-selection-row":
                assert outcome == {"mode": "full", "suites": [], "reasons": ["unmapped.txt"]}, (label, outcome)

        cutover_imports = _imported_local_modules(cutover_path)
        outcome_imports = _imported_local_modules(outcome_path)
        shared_loop_helpers = {
            name
            for name in (cutover_imports & outcome_imports)
            if (LOOP / f"{name}.py").is_file()
        }
        assert "build_selection_outcome" in cutover_imports or shared_loop_helpers, (
            "loop/build_cutover.py reimplements publication acceptance independently of "
            "loop/build_selection_outcome.py instead of delegating to one shared acceptance function"
        )

        cutover_defs = {
            node.name
            for node in ast.walk(ast.parse(cutover_path.read_text(encoding="utf-8")))
            if isinstance(node, ast.FunctionDef)
        }
        assert not ({"_verified_manifest", "_row_key"} <= cutover_defs), (
            "loop/build_cutover.py still defines its own duplicate manifest/row validator "
            "beside loop/build_selection_outcome.py"
        )


def _formal_section_11_table_rows() -> list[str]:
    """Return Markdown table rows from section 11 (Independent oracles) of docs/formal.md."""
    formal = (ROOT / "docs" / "formal.md").read_text(encoding="utf-8")
    marker = "## 11. Independent oracles"
    assert marker in formal, "docs/formal.md is missing section 11 (Independent oracles)"
    section = formal.split(marker, 1)[1].split("\n## ", 1)[0]
    return [line.strip() for line in section.splitlines() if line.strip().startswith("|")]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="extra: decisions/code-does-not-decide.md: loop/status_times.py and "
           "loop/flow_evidence.py must be removed from production loop/ with zero production "
           "imports; loop/tests/flow_evidence.py must remain as a fate-(b) independent test "
           "oracle recorded in docs/formal.md section 11, and loop/tests/status_times.py "
           "must either be retired or recorded in its own docs/formal.md section 11 row.",
)
def test_status_times_and_flow_evidence_are_not_live_calculators_in_production_loop():
    from rezono_compiler import pack, rules

    # Confirm the std-loop pack rules already carry both decisions.
    derived = set(rules.load(pack.read(STD_LOOP).rules).derived())
    required_pack_relations = {
        "delivery_waiting_time",
        "delivery_completed_at",
        "flow_case_verdict",
        "flow_case_incomplete",
    }
    assert required_pack_relations <= derived, (
        f"packs/std-loop missing required relations: {sorted(required_pack_relations - derived)}"
    )

    # Neither calculator may live in production loop/.
    for name in ("status_times.py", "flow_evidence.py"):
        assert not (LOOP / name).exists(), (
            f"loop/{name} still computes live decisions in production loop/ beside packs/std-loop; "
            f"remove the production module while keeping fate-(b) test-only oracles under loop/tests/"
        )

    # No production file under loop/ may import or dynamically execute either module.
    for path in _production_loop_python_files():
        imports = _imported_local_modules(path)
        for stem in ("status_times", "flow_evidence"):
            assert stem not in imports and not _references_module_dynamically(path, stem), (
                f"production module {path.relative_to(ROOT).as_posix()} imports or loads {stem!r}"
            )

    # flow_evidence.py is a required fate-(b) oracle under loop/tests/ (never deleted).
    flow_oracle = LOOP / "tests" / "flow_evidence.py"
    assert flow_oracle.is_file(), (
        "moved test-only oracle loop/tests/flow_evidence.py is missing; "
        "keep the independent test oracle under loop/tests/"
    )

    # docs/formal.md section 11 (Independent oracles) must record every test oracle present under
    # loop/tests/ in its own table row, and never reference the retired production module paths.
    oracle_rows = _formal_section_11_table_rows()
    assert oracle_rows, "docs/formal.md section 11 (Independent oracles) table is empty"
    assert any("(../loop/tests/flow_evidence.py)" in row for row in oracle_rows), (
        "docs/formal.md section 11 table must record the independent test oracle at "
        "../loop/tests/flow_evidence.py"
    )

    status_oracle = LOOP / "tests" / "status_times.py"
    has_status_row = any("(../loop/tests/status_times.py)" in row for row in oracle_rows)
    if status_oracle.is_file():
        assert has_status_row, (
            "loop/tests/status_times.py is kept as a test oracle, so docs/formal.md section 11 "
            "must record it in its own table row (../loop/tests/status_times.py)"
        )
    else:
        assert not has_status_row, (
            "docs/formal.md section 11 still references ../loop/tests/status_times.py after retirement"
        )

    for retired_link in ("(../loop/flow_evidence.py)", "(../loop/status_times.py)"):
        assert not any(retired_link in row for row in oracle_rows), (
            f"docs/formal.md section 11 table still references retired production module {retired_link}"
        )
