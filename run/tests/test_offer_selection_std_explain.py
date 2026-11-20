"""offer-selection takes its explanation question from std-explain (decisions/standard-packs-everywhere.md, section 3).

The pack copied std-explain's `grounds` question because it did not import the pack. invoice-drift imports
std-explain and its reader names `proof: grounds` without a copy; offer-selection does the same.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
OFFER = REPO / "run" / "packs" / "offer-selection"
STD_EXPLAIN = REPO / "packs" / "std-explain"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/standard-packs-everywhere.md, section 3. Import std-explain in "
    "run/packs/offer-selection/pack.yaml, pinned to its sha256, and drop the copied grounds question from its "
    "questions.yaml; the physical-or-nested reader keeps proof: grounds."))
def test_offer_selection_imports_std_explain():
    manifest = yaml.safe_load((OFFER / "pack.yaml").read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest.get("imports") or ()}
    assert "std-explain" in by_name, "run/packs/offer-selection/pack.yaml must import std-explain"
    entry = by_name["std-explain"]
    assert (OFFER / entry["path"]).resolve() == STD_EXPLAIN.resolve(), "the import must point to packs/std-explain"
    assert re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))), "the import must pin a 64-hex sha256"

    own = yaml.safe_load((OFFER / "questions.yaml").read_text(encoding="utf-8")) or {}
    copied = [question.get("term") for question in own.get("questions") or ()]
    assert not copied, f"offer-selection still states explanation questions of its own: {copied}"

    from rezono_compiler import modules, pack

    assert entry["sha256"] == modules.pack_hash(STD_EXPLAIN), "the std-explain pin does not match packs/std-explain"
    model = pack.read(OFFER)
    assert [question.get("term") for question in model.questions].count("grounds") == 1
    readers = {reader.get("id"): reader for reader in model.reader_questions}
    assert (readers.get("physical-or-nested") or {}).get("proof") == "grounds"
