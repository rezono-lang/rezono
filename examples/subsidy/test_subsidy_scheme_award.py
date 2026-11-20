"""Whole-calculation acceptance for examples/subsidy-scheme/rezono/award.rezono.

Compares the live examples/subsidy-scheme pack (with award.rezono, its generated award.json and
rezono: in pack.yaml, and without calc/award.yaml) against the legacy calc/award.yaml oracle
kept in fixtures/award-legacy.yaml, verifies examples/subsidy produces the exact expected/calc/
outcomes across every scenario state, and verifies every reference to calc/award.yaml is updated
(decisions/language-calculations.md).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from calcsupport import run_both
from rezono_compiler import calc, calc_sql, emit, modules, pack, scenarios


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SCHEME = REPO / "examples" / "subsidy-scheme"
SUBSIDY = REPO / "examples" / "subsidy"
ORACLE = HERE / "fixtures" / "award-legacy.yaml"

UPDATED_REFERENCES = (
    "compiler/tests/rezono/test_lower_calculation.py",
    "compiler/tests/rezono/calc_packs.py",
    "compiler/tests/rezono/test_lower_parameters.py",
    "docs/tutorial.md",
    "examples/subsidy-scheme/README.md",
    "examples/subsidy/README.md",
    "examples/subsidy-scheme/rules/findings.dl",
    "examples/subsidy-scheme/candidate/findings.rezono",
    "examples/subsidy-scheme/candidate/findings.json",
    "examples/subsidy/reference.py",
    "examples/subsidy/calc/date.yaml",
    "examples/subsidy/facts/scheme.yaml",
    "examples/subsidy/test_whole_subsidy_scheme_schema.py",
)


class MissingSubsidyAwardInRezono(AssertionError):
    """examples/subsidy-scheme award is not yet converted to rezono/award.rezono with updated references."""


def golden_calc_text(results: dict[str, dict]) -> str:
    """Serialize per-rule calculation outcomes in the exact format of expected/calc/*.json."""
    out = {
        rule: {str(subject): (value[1] if value[0] == "known" else value[0]) for subject, value in sorted(subjects.items())}
        for rule, subjects in sorted(results.items())
    }
    return json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def compile_legacy_oracle(tmp_path: Path) -> dict[str, str]:
    """Compile an isolated copy of examples/subsidy-scheme using the frozen legacy calc/award.yaml."""
    root = tmp_path / "legacy-oracle"
    shutil.copytree(REPO / "packs" / "std-decision", root / "packs" / "std-decision",
                    ignore=shutil.ignore_patterns("candidate"))
    scheme = root / "examples" / "subsidy-scheme"
    shutil.copytree(SCHEME, scheme, ignore=shutil.ignore_patterns("candidate", "rezono"))
    (scheme / "calc").mkdir(exist_ok=True)
    shutil.copy2(ORACLE, scheme / "calc" / "award.yaml")
    meta_path = scheme / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    meta.pop("rezono", None)
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return emit.compile_pack(pack.read(scheme))


def test_award_legacy_oracle_matches_existing_calc_yaml():
    """While calc/award.yaml still exists, the frozen oracle fixture holds identical bytes."""
    live = SCHEME / "calc" / "award.yaml"
    if live.is_file():
        assert live.read_bytes().replace(b"\r\n", b"\n") == ORACLE.read_bytes().replace(b"\r\n", b"\n")


@pytest.mark.xfail(
    strict=True,
    raises=MissingSubsidyAwardInRezono,
    reason=(
        "extra: decisions/language-calculations.md: Convert examples/subsidy-scheme/calc/award.yaml "
        "to examples/subsidy-scheme/rezono/award.rezono (starting from candidate/award.rezono) with "
        "its generated rezono/award.json and rezono: entry in pack.yaml, remove calc/award.yaml, "
        "verify identical ir/calc.json and examples/subsidy expected/calc/ outcomes, re-pin "
        "examples/subsidy/pack.yaml sha256, and update every listed reference to calc/award.yaml."
    ),
)
def test_subsidy_scheme_award_in_rezono(tmp_path):
    problems: list[str] = []

    award_source = SCHEME / "rezono" / "award.rezono"
    award_form = SCHEME / "rezono" / "award.json"
    legacy_yaml = SCHEME / "calc" / "award.yaml"

    if not award_source.is_file():
        problems.append("missing examples/subsidy-scheme/rezono/award.rezono")
    if not award_form.is_file():
        problems.append("missing examples/subsidy-scheme/rezono/award.json")
    if legacy_yaml.exists():
        problems.append("examples/subsidy-scheme/calc/award.yaml must be removed once award.rezono is live")

    scheme_meta = yaml.safe_load((SCHEME / "pack.yaml").read_bytes())
    rezono_entries = scheme_meta.get("rezono") or []
    award_entries = [
        entry for entry in rezono_entries
        if isinstance(entry, dict)
        and entry.get("module") == "rezono/award.rezono"
        and entry.get("form") == "rezono/award.json"
    ]
    if not award_entries:
        problems.append("examples/subsidy-scheme/pack.yaml must declare rezono/award.rezono and rezono/award.json")

    subsidy_meta = yaml.safe_load((SUBSIDY / "pack.yaml").read_bytes())
    scheme_pin = next(
        (entry.get("sha256") for entry in subsidy_meta.get("imports") or [] if entry.get("name") == "subsidy-scheme"),
        None,
    )
    actual_hash = modules.pack_hash(SCHEME)
    if scheme_pin != actual_hash:
        problems.append(f"examples/subsidy/pack.yaml pin {scheme_pin!r} != subsidy-scheme pack_hash {actual_hash!r}")

    stale_refs = [
        rel for rel in UPDATED_REFERENCES
        if "calc/award.yaml" in (REPO / rel).read_text(encoding="utf-8")
    ]
    if stale_refs:
        problems.append(f"stale references to calc/award.yaml in: {stale_refs}")

    tutorial_text = (REPO / "docs" / "tutorial.md").read_text(encoding="utf-8")
    if "examples/subsidy-scheme/rezono/award.rezono" not in tutorial_text:
        problems.append("docs/tutorial.md must link to examples/subsidy-scheme/rezono/award.rezono")

    tutorial_test_text = (SUBSIDY / "test_tutorial.py").read_text(encoding="utf-8")
    if '"rezono"' not in tutorial_test_text and "'rezono'" not in tutorial_test_text:
        problems.append("examples/subsidy/test_tutorial.py must include rezono/ when checking quoted tutorial lines")

    if problems:
        raise MissingSubsidyAwardInRezono("\n".join(problems))

    # Live pack compiles cleanly (which also verifies award.json against write-form.ts) and matches legacy IR + SQL.
    try:
        live_files = emit.compile_pack(pack.read(SCHEME))
    except pack.CompileError as error:
        raise MissingSubsidyAwardInRezono(f"compiling examples/subsidy-scheme failed: {error}") from error

    legacy_files = compile_legacy_oracle(tmp_path)
    if live_files["ir/calc.json"] != legacy_files["ir/calc.json"]:
        raise MissingSubsidyAwardInRezono("ir/calc.json from rezono/award.rezono differs from legacy calc/award.yaml")
    if live_files["engine/calc.sql"] != legacy_files["engine/calc.sql"]:
        raise MissingSubsidyAwardInRezono("engine/calc.sql from rezono/award.rezono differs from legacy calc/award.yaml")

    # End-to-end subsidy evaluation across every scenario state matches expected/calc/*.json byte-for-byte.
    model = pack.read(SUBSIDY)
    program = calc.build(model, model.calc)
    evaluation_rows = {table: [tuple(row.values()) for row in rows] for table, rows in calc_sql.rows(program).items()}
    expected_dir = SUBSIDY / "expected" / "calc"
    expected_files = sorted(expected_dir.glob("*.json"))
    seen_labels: list[str] = []
    for label, rows in scenarios.states(model, SUBSIDY):
        seen_labels.append(label)
        got, exact = run_both(model, program, model.calc, rows | evaluation_rows)
        if got != exact:
            raise MissingSubsidyAwardInRezono(f"{label}: DuckDB and exact Python calculation results disagree")
        want = expected_dir / f"{label}.json"
        if not want.is_file():
            raise MissingSubsidyAwardInRezono(f"missing expected calc file: {want.relative_to(REPO)}")
        if golden_calc_text(got) != want.read_text(encoding="utf-8"):
            raise MissingSubsidyAwardInRezono(f"{label}: calculation output differs from {want.relative_to(REPO)}")
    if [path.stem for path in expected_files] != seen_labels:
        raise MissingSubsidyAwardInRezono(
            f"expected/calc labels {[path.stem for path in expected_files]} != evaluated {seen_labels}"
        )
