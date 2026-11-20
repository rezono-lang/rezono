"""Staged candidate acceptance for packs/std-decision (decisions/language-standard-pack-candidates.md).

Compares packs/std-decision in its existing LinkML + Datalog form (the live oracle) against the staged Rezono
candidate in packs/std-decision/candidate/decision.{rezono,json} on semantic bundle, compiled rule IR and SQL,
and DuckDB batch evaluation over representative decision scenarios and counter-cases.
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


STD = REPO / "packs/std-decision"
SCENARIO = {
    "decision": [("d1",), ("d2",), ("d3",), ("d4",)],
    "decision__state": [("d1", "in_force"), ("d2", "in_force"), ("d3", "in_force"), ("d4", "proposed")],
    "decision__supersedes": [("d2", "d1")],
    "decision__decider": [("d1", "board"), ("d2", "board")],
    "decision__valid_from_day": [("d1", 20260101), ("d2", 20260201), ("d3", 20260301), ("d4", 20260101)],
    "decision__valid_until_day": [("d3", 20260201)],
    "reference_date__day": [("r1", 20260115), ("r2", 20260215), ("r3", 20260401)],
    "ground__decision": [("g1", "d2")],
    "ground__rests_on": [("g1", "d1")],
}


def check_pack(tmp_path: Path, form: str) -> tuple[dict, dict]:
    directory = isolated_standard_pack(STD, tmp_path, form, "decision")
    meaning = compiled_meaning(directory, "std-decision", "decision")
    evaluated = evaluate_batch(directory, SCENARIO)
    return meaning, evaluated


def test_std_decision_legacy_evaluates_scenarios(tmp_path):
    _, evaluated = check_pack(tmp_path, "legacy")
    assert ("d1", "r1") in evaluated["in_force_on"]
    assert ("d2", "r2") in evaluated["in_force_on"]
    # Counter-cases: superseded d1 is no longer in force at r2; proposed d4 never takes effect;
    # d3 triggers both window_inverted and in_force_without_decider (when its start has passed).
    assert ("d1", "r2") not in evaluated["in_force_on"]
    assert ("d4", "r1") not in evaluated["in_force_on"]
    assert ("d3",) in evaluated["window_inverted"]
    assert ("d2", "d1") in evaluated["ground_chain"]
    assert ("d4",) in evaluated["proposal"]


@pytest.mark.xfail(
    strict=True,
    raises=MissingCandidatePack,
    reason="M3: decisions/language-standard-pack-candidates.md: Author packs/std-decision/candidate/decision.rezono "
           "and generate packs/std-decision/candidate/decision.json with node rezono/src/write-form.ts so that the "
           "isolated candidate matches packs/std-decision on semantic bundle, compiled SQL/IR and batch evaluation. "
           "Keep schema/decision.yaml and rules/decision.dl untouched as the oracle. Read "
           "decisions/language-standard-pack-candidates.md and decisions/language-first-packs.md.",
)
def test_whole_std_decision_candidate_has_the_same_meaning(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
