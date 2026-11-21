"""Staged schema-and-rules candidate acceptance for examples/subsidy.

Compares examples/subsidy in its existing LinkML + Datalog form (keeping facts/*.yaml and calc/*.yaml intact in
both forms while calculations lower separately) against the staged Rezono candidate in
examples/subsidy/candidate/ holding credentials.{rezono,json} (schema + rules/credentials.dl),
reference.{rezono,json} (schema/reference.yaml), and rule modules access, home and ledger.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, facts, pack
from support import text, violations
from candidate_pack import (
    MissingCandidatePack,
    REPO,
    legacy_helpers,
    unplaced,
    verify_candidate_forms,
)


SUBSIDY = REPO / "examples/subsidy"
MODULES = (
    ("credentials", "observation"),
    ("reference", "observation"),
    ("access", "facts"),
    ("home", "facts"),
    ("ledger", "facts"),
)
MODULE_NAMES = tuple(name for name, _ in MODULES)
SOURCES = {
    "schema/credentials.yaml",
    "schema/reference.yaml",
    *(f"rules/{name}.dl" for name in ("access", "credentials", "home", "ledger")),
    *(f"rezono/{name}.rezono" for name in MODULE_NAMES),
}


def isolated(tmp_path: Path, form: str) -> Path:
    root = tmp_path / form
    legacy_helpers().materialize_legacy_packs(
        root,
        ("packs", "examples/subsidy-scheme", "examples/subsidy"),
        prefer_live=True,
    )
    target = root / "examples/subsidy"
    shutil.copytree(SUBSIDY / "facts", target / "facts", dirs_exist_ok=True)
    if form == "legacy":
        return target
    verify_candidate_forms(SUBSIDY, MODULE_NAMES, tmp_path)
    shutil.rmtree(target / "schema", ignore_errors=True)
    shutil.rmtree(target / "rules", ignore_errors=True)
    shutil.rmtree(target / "rezono", ignore_errors=True)
    shutil.copytree(SUBSIDY / "candidate", target / "rezono")
    meta_path = target / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    meta["rezono"] = [
        {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": layer}
        for name, layer in MODULES
    ]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


def check_pack(tmp_path: Path, form: str) -> dict:
    directory = isolated(tmp_path, form)
    with ExitStack() as stack:
        legacy_helpers().admit_legacy_std_packs(stack, directory.parents[1])
        model = pack.read(directory)
        files = emit.compile_pack(model)
    checked_violations = {}
    for fact_file in sorted((directory / "facts").glob("*.yaml")):
        if fact_file.name.endswith(".sources.yaml"):
            continue
        rows = facts.load(model, fact_file)
        findings = violations(files, rows)
        expected_path = SUBSIDY / "expected/violations" / f"{fact_file.stem}.json"
        expected = json.loads(expected_path.read_text(encoding="utf-8"))
        assert findings == text({k: {tuple(r) for r in v} for k, v in expected.items()}), fact_file.stem
        checked_violations[fact_file.stem] = findings
    return {
        "files": sorted(files),
        "bundle": unplaced(json.loads(files["bundle/schema-bundle.json"]), "subsidy", SOURCES),
        "ir": unplaced(json.loads(files["ir/rules.json"]), "subsidy", SOURCES),
        "calc_ir": files["ir/calc.json"],
        "tables_sql": files["engine/tables.sql"],
        "integrity_sql": files["engine/integrity.sql"],
        "rules_sql": files["engine/rules.sql"],
        "batch_sql": files["batch/rules.sql"],
        "violations": checked_violations,
    }


def test_subsidy_legacy_compiles_and_checks_facts(tmp_path):
    got = check_pack(tmp_path, "legacy")
    own = [(s["name"], s["module"]) for s in got["bundle"]["schemas"] if s.get("pack") == "subsidy"]
    assert own == [("subsidy_credentials", "credentials"), ("subsidy_reference", "reference")]
    assert set(got["violations"]) == {"applications", "credentials", "ledger", "population", "roles", "scheme"}


def test_whole_subsidy_schema_and_rules_candidate(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
