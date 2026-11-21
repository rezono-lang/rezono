"""Staged candidate acceptance for examples/projects (decisions/language-standard-pack-candidates.md).

Compares examples/projects in its existing LinkML + YAML facts form (the live oracle, plus the checked-in
expected violation sets) against the staged Rezono candidate in examples/projects/candidate/ holding
projects.{rezono,json}, valid.{rezono,json} and errors.{rezono,json}.
"""

from __future__ import annotations

from collections import Counter
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


PROJECTS = REPO / "examples/projects"
DATASETS = ("valid", "errors")
MODULES = ("projects", *DATASETS)


def isolated(tmp_path: Path, form: str) -> Path:
    root = tmp_path / form
    legacy_helpers().materialize_legacy_packs(root, ("examples/projects",), prefer_live=True)
    directory = root / "examples/projects"
    if form != "legacy":
        shutil.rmtree(directory / "schema", ignore_errors=True)
        shutil.rmtree(directory / "facts", ignore_errors=True)
        shutil.rmtree(directory / "rezono", ignore_errors=True)
        verify_candidate_forms(PROJECTS, MODULES, tmp_path)
        shutil.copytree(PROJECTS / "candidate", directory / "rezono")
        meta_path = directory / "pack.yaml"
        meta = yaml.safe_load(meta_path.read_bytes())
        meta["rezono"] = [
            {"module": f"rezono/{name}.rezono", "form": f"rezono/{name}.json", "layer": "facts"}
            for name in MODULES
        ]
        meta_path.write_text(yaml.safe_dump(meta, sort_keys=False), encoding="utf-8")
    return directory


def check_example(directory: Path) -> tuple[dict, dict]:
    model = pack.read(directory)
    files = emit.compile_pack(model)
    sources = {"schema/projects.yaml", "rezono/projects.rezono"}
    bundle = unplaced(json.loads(files["bundle/schema-bundle.json"]), "projects", sources)
    assert bundle["rules"] == []
    assert [eq["id"] for eq in bundle["path_equations"]] == ["task.same_project"]
    assert {uk["id"] for uk in bundle["unique_keys"]} == {"project.project_name", "dependency.dependency_pair"}
    datasets = facts.files(directory)
    assert Counter(path.stem for path in datasets) == Counter(DATASETS)
    results = {}
    for path in sorted(datasets, key=lambda p: p.stem):
        rows = facts.load(model, path)
        findings = violations(files, rows)
        expected = json.loads((PROJECTS / "expected/violations" / f"{path.stem}.json").read_text(encoding="utf-8"))
        assert findings == text({name: {tuple(row) for row in matches} for name, matches in expected.items()})
        results[path.stem] = (rows, findings)
    return bundle, results


def test_authored_projects_has_expected_states(tmp_path):
    _, results = check_example(isolated(tmp_path, "legacy"))
    # Positive dataset has zero violations; counter-case dataset exercises path_equation, unique_key, value_range.
    assert results["valid"][1] == {}
    assert "task__same_project__path_equation" in results["errors"][1]
    assert "project__project_name__unique" in results["errors"][1]
    assert "budget_line__amount__value_range" in results["errors"][1]


def test_whole_projects_candidate_has_the_same_meaning(tmp_path):
    actual = check_example(isolated(tmp_path, "candidate"))
    expected = check_example(isolated(tmp_path, "legacy"))
    assert actual == expected
