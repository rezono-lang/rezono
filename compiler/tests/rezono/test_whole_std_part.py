"""Staged candidate acceptance for packs/std-part (decisions/language-standard-pack-candidates.md).

Compares packs/std-part in its existing LinkML + Datalog form (the live oracle) against the staged Rezono
candidate in packs/std-part/candidate/part.{rezono,json} on semantic bundle (including functionality and
value_range schema checks), compiled rule IR and SQL, and DuckDB batch evaluation over forest and cycle cases.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from candidate_pack import (
    MissingCandidatePack,
    REPO,
    compiled_meaning,
    evaluate_batch,
    isolated_standard_pack,
)


STD = REPO / "packs/std-part"
SCENARIO = {
    "constituent__part_of": [("c", "b"), ("b", "a"), ("d", "a"), ("x", "y"), ("y", "x")],
}


def check_pack(tmp_path: Path, form: str) -> tuple[dict, dict]:
    directory = isolated_standard_pack(STD, tmp_path, form, "part")
    meaning = compiled_meaning(directory, "std-part", "part")
    evaluated = evaluate_batch(directory, SCENARIO)
    return meaning, evaluated


def test_std_part_legacy_evaluates_scenarios(tmp_path):
    meaning, evaluated = check_pack(tmp_path, "legacy")
    checks = {c["view"]: c["relation"] for c in meaning["bundle"]["checks"]}
    assert checks["constituent__part_of__functionality"] == "rezono__functionality"
    assert checks["constituent__repeat__value_range"] == "rezono__value_range"
    assert ("c", "a") in evaluated["within"] and ("c", "a") in evaluated["outermost"]
    # Counter-cases: intermediate whole b is not outermost; cycle x-y triggers part_cycle; root a has no cycle.
    assert ("c", "b") not in evaluated["outermost"]
    assert ("x",) in evaluated["part_cycle"] and ("y",) in evaluated["part_cycle"]
    assert ("a",) not in evaluated["part_cycle"]


@pytest.mark.xfail(
    strict=True,
    raises=MissingCandidatePack,
    reason="M3: decisions/language-standard-pack-candidates.md: Author packs/std-part/candidate/part.rezono "
           "and generate packs/std-part/candidate/part.json with node rezono/src/write-form.ts so that the "
           "isolated candidate matches packs/std-part on semantic bundle, compiled SQL/IR and batch evaluation. "
           "Keep schema/part.yaml and rules/part.dl untouched as the oracle. Read "
           "decisions/language-standard-pack-candidates.md and decisions/language-first-packs.md.",
)
def test_whole_std_part_candidate_has_the_same_meaning(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
