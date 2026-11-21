"""Staged schema-and-rules candidate acceptance for examples/subsidy-scheme.

Compares examples/subsidy-scheme in its existing LinkML + Datalog form (keeping the award calculation intact in both
forms while calculations lower separately) against the staged Rezono candidate in
examples/subsidy-scheme/candidate/ holding subsidy.{rezono,json} and the rule modules
assessment, costs, findings and scheme.
"""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
import json
import shutil

import pytest
import yaml

from rezono_compiler import emit, pack
from candidate_pack import (
    MissingCandidatePack,
    REPO,
    legacy_helpers,
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
    legacy_helpers().materialize_legacy_packs(
        root,
        ("packs/std-decision", "examples/subsidy-scheme"),
    )
    target = root / "examples/subsidy-scheme"
    if form == "legacy":
        return target
    verify_candidate_forms(SCHEME, MODULES, tmp_path)
    shutil.rmtree(target / "schema", ignore_errors=True)
    shutil.rmtree(target / "rules", ignore_errors=True)
    rezono_dir = target / "rezono"
    rezono_dir.mkdir(exist_ok=True)
    for name in MODULES:
        shutil.copy2(SCHEME / "candidate" / f"{name}.rezono", rezono_dir / f"{name}.rezono")
        shutil.copy2(SCHEME / "candidate" / f"{name}.json", rezono_dir / f"{name}.json")
    meta_path = target / "pack.yaml"
    meta = yaml.safe_load(meta_path.read_bytes())
    existing = list(meta.get("rezono") or [])
    existing_modules = {entry["module"] for entry in existing}
    meta["rezono"] = existing + [
        {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"}
        for name in MODULES
        if f"rezono/{name}.rezono" not in existing_modules
    ]
    meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return target


def compiled(tmp_path: Path, form: str) -> dict:
    directory = isolated(tmp_path, form)
    with ExitStack() as stack:
        legacy_helpers().admit_legacy_std_packs(stack, directory.parents[1])
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
