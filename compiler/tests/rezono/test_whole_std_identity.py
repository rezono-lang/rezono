"""Staged candidate acceptance for packs/std-identity (decisions/language-standard-pack-candidates.md).

Compares packs/std-identity in its existing LinkML + Datalog form (the live oracle) against the staged Rezono
candidate in packs/std-identity/candidate/identity.{rezono,json} on semantic bundle, compiled rule IR and SQL,
and DuckDB batch evaluation over representative equivalence, representative and conflict cases.
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


STD = REPO / "packs/std-identity"
SCENARIO = {
    "referent": [("a",), ("b",), ("c",), ("d",), ("e",), ("f",), ("solo",)],
    "referent__same_as": [("a", "b"), ("c", "d"), ("e", "f")],
    "referent__represented_by": [("a", "a"), ("e", "e"), ("f", "f"), ("c", "solo")],
}


def check_pack(tmp_path: Path, form: str) -> tuple[dict, dict]:
    directory = isolated_standard_pack(STD, tmp_path, form, "identity")
    meaning = compiled_meaning(directory, "std-identity", "identity")
    evaluated = evaluate_batch(directory, SCENARIO)
    return meaning, evaluated


def test_std_identity_legacy_evaluates_scenarios(tmp_path):
    _, evaluated = check_pack(tmp_path, "legacy")
    assert ("a", "b") in evaluated["equivalent"] and ("b", "a") in evaluated["equivalent"]
    assert ("b", "a") in evaluated["representative"]
    assert ("solo", "solo") in evaluated["representative"]
    # Counter-cases: disputed class {e, f} gets no representative and fires representatives_disagree;
    # c naming outside member solo fires representative_outside_class; unrelated nodes are not equivalent.
    assert ("e", "e") not in evaluated["representative"]
    assert ("e", "f") in evaluated["representatives_disagree"]
    assert ("c", "solo") in evaluated["representative_outside_class"]
    assert ("a", "solo") not in evaluated["equivalent"]


@pytest.mark.xfail(
    strict=True,
    raises=MissingCandidatePack,
    reason="M3: decisions/language-standard-pack-candidates.md: Author packs/std-identity/candidate/identity.rezono "
           "and generate packs/std-identity/candidate/identity.json with node rezono/src/write-form.ts so that the "
           "isolated candidate matches packs/std-identity on semantic bundle, compiled SQL/IR and batch evaluation. "
           "Keep schema/identity.yaml and rules/identity.dl untouched as the oracle. Read "
           "decisions/language-standard-pack-candidates.md and decisions/language-first-packs.md.",
)
def test_whole_std_identity_candidate_has_the_same_meaning(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
