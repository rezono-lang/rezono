"""Staged candidate acceptance for packs/std-order (decisions/language-standard-pack-candidates.md).

Compares packs/std-order in its existing LinkML + Datalog form (the live oracle) against the staged Rezono
candidate in packs/std-order/candidate/order.{rezono,json} on semantic bundle, compiled rule IR and SQL,
and DuckDB batch evaluation over chain, diamond, cycle and rank-conflict cases.
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


STD = REPO / "packs/std-order"
SCENARIO = {
    "ordered__precedes": [("a", "b"), ("b", "c"), ("b", "d"), ("x", "y"), ("y", "x")],
    "ordered__rank": [("a", 1), ("b", 2), ("c", 5), ("x", 3), ("y", 1)],
}


def check_pack(tmp_path: Path, form: str) -> tuple[dict, dict]:
    directory = isolated_standard_pack(STD, tmp_path, form, "order")
    meaning = compiled_meaning(directory, "std-order", "order")
    evaluated = evaluate_batch(directory, SCENARIO)
    return meaning, evaluated


def test_std_order_legacy_evaluates_scenarios(tmp_path):
    _, evaluated = check_pack(tmp_path, "legacy")
    assert ("a", "c") in evaluated["before"] and ("a", "d") in evaluated["before"]
    assert ("c", "a") in evaluated["comparable"]
    # Counter-cases: c and d are incomparable; x-y forms an order_cycle and rank_conflict; a-b has no rank conflict.
    assert ("c", "d") not in evaluated["comparable"]
    assert ("x",) in evaluated["order_cycle"] and ("y",) in evaluated["order_cycle"]
    assert ("x", "y") in evaluated["rank_conflict"]
    assert ("a", "b") not in evaluated["rank_conflict"]


@pytest.mark.xfail(
    strict=True,
    raises=MissingCandidatePack,
    reason="M3: decisions/language-standard-pack-candidates.md: Author packs/std-order/candidate/order.rezono "
           "and generate packs/std-order/candidate/order.json with node rezono/src/write-form.ts so that the "
           "isolated candidate matches packs/std-order on semantic bundle, compiled SQL/IR and batch evaluation. "
           "Keep schema/order.yaml and rules/order.dl untouched as the oracle. Read "
           "decisions/language-standard-pack-candidates.md and decisions/language-first-packs.md.",
)
def test_whole_std_order_candidate_has_the_same_meaning(tmp_path):
    actual = check_pack(tmp_path, "candidate")
    expected = check_pack(tmp_path, "legacy")
    assert actual == expected
