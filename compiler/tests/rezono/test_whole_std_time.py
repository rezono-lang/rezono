"""Staged candidate acceptance for packs/std-time (decisions/language-standard-pack-candidates.md).

Compares packs/std-time in its existing LinkML + Datalog form (the live oracle) against the staged Rezono
candidate in packs/std-time/candidate/time.{rezono,json} on semantic bundle (including enum metadata, mappings,
open-world slots and Axis explain: fold annotation), compiled rule IR and SQL, and DuckDB batch evaluation over
Allen relations, judgements, open-world unknown bounds and axiom violations.
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


STD = REPO / "packs/std-time"
SCENARIO = {
    "interval__on_axis": [("i1", "cal"), ("i2", "cal"), ("i3", "cal"), ("i4", "cal")],
    "interval__start": [("i1", 10), ("i2", 20), ("i3", 10), ("i4", 50)],
    "interval__end": [("i1", 30), ("i2", 40), ("i4", 40)],
    "interval__extension_end": [],
    "interval__known_from": [("i1", 1)],
    "interval__in_series": [("i1", "s1"), ("i2", "s1")],
    "interval__unbounded": [],
    "reference_point__on_axis": [("r1", "cal")],
    "reference_point__position": [("r1", 15)],
    "reference_point__horizon": [("r1", 5)],
}


def check_pack(tmp_path: Path, form: str) -> tuple[dict, dict]:
    directory = isolated_standard_pack(STD, tmp_path, form, "time")
    meaning = compiled_meaning(directory, "std-time", "time")
    evaluated = evaluate_batch(directory, SCENARIO)
    return meaning, evaluated


def test_std_time_legacy_evaluates_scenarios(tmp_path):
    _, evaluated = check_pack(tmp_path, "legacy")
    assert ("i1", "i2", "overlaps") in evaluated["allen"]
    assert ("i1", "r1", "positive", "end_beyond_horizon") in evaluated["judgement"]
    # Counter-cases: i3 has an unrecorded end (open world -> unknown, never holds); i4 is inverted.
    assert ("i3",) in evaluated["end_not_recorded"]
    assert ("i3", "r1", "unknown", "end_not_recorded") in evaluated["judgement"]
    assert ("i3", "r1") not in evaluated["holds_at"]
    assert ("i4",) in evaluated["interval_inverted"]


def test_whole_std_time_candidate_has_the_same_meaning(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
