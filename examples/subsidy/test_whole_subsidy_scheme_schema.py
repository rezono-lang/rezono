"""Staged schema-and-rules candidate acceptance for examples/subsidy-scheme.

Compares examples/subsidy-scheme in its existing LinkML + Datalog form (keeping calc/award.yaml intact in both
forms while calculations lower separately) against the staged Rezono candidate in
examples/subsidy-scheme/candidate/ holding subsidy.{rezono,json} and the rule modules
assessment, costs, findings and scheme.
"""

from __future__ import annotations

from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, pack
from candidate_pack import (
    MissingCandidatePack,
    REPO,
    unplaced,
    verify_candidate_forms,
)


SCHEME = REPO / "examples/subsidy-scheme"
MODULES = ("subsidy", "assessment", "costs", "findings", "scheme")
SOURCES = {
    "schema/subsidy.yaml",
    *(f"rules/{name}.dl" for name in ("assessment", "costs", "findings", "scheme")),
    *(f"rezono/{name}.rezono" for name in MODULES),
}


def isolated(tmp_path: Path, form: str) -> Path:
    root = tmp_path / form
    shutil.copytree(REPO / "packs/std-decision", root / "packs/std-decision", ignore=shutil.ignore_patterns("candidate"))
    target = root / "examples/subsidy-scheme"
    shutil.copytree(SCHEME, target, ignore=shutil.ignore_patterns("candidate"))
    if form == "legacy":
        return target
    verify_candidate_forms(SCHEME, MODULES, tmp_path)
    shutil.rmtree(target / "schema", ignore_errors=True)
    shutil.rmtree(target / "rules", ignore_errors=True)
    shutil.copytree(SCHEME / "candidate", target / "rezono")
    meta_path = target / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    meta["rezono"] = [
        {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"}
        for name in MODULES
    ]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


def compiled(tmp_path: Path, form: str) -> dict:
    directory = isolated(tmp_path, form)
    files = emit.compile_pack(pack.read(directory))
    # Every file except schema-bundle.json and ir/rules.json (whose spans/origins name the source file) matches
    # byte-for-byte; schema-bundle.json and ir/rules.json match after normalising own source spans/origins.
    return {
        "files": sorted(files),
        "bundle": unplaced(json.loads(files["bundle/schema-bundle.json"]), "subsidy-scheme", SOURCES),
        "ir": unplaced(json.loads(files["ir/rules.json"]), "subsidy-scheme", SOURCES),
        "calc_ir": files["ir/calc.json"],
        "tables_sql": files["engine/tables.sql"],
        "integrity_sql": files["engine/integrity.sql"],
        "rules_sql": files["engine/rules.sql"],
        "batch_sql": files["batch/rules.sql"],
        "calc_sql": files["engine/calc.sql"],
    }


def test_subsidy_scheme_legacy_compiles_with_calc_and_rules(tmp_path):
    got = compiled(tmp_path, "legacy")
    own = [s for s in got["bundle"]["schemas"] if s.get("pack") == "subsidy-scheme"]
    assert [(s["name"], s["module"]) for s in own] == [("subsidy", "subsidy")]
    assert "engine/calc.sql" in got["files"] and "ir/rules.json" in got["files"]
    assert len(got["ir"]["rules"]) > 0


def test_whole_subsidy_scheme_schema_and_rules_candidate(tmp_path):
    actual = compiled(tmp_path, "candidate")
    expected = compiled(tmp_path, "legacy")
    assert actual == expected
