"""cleanup-deadline is a std-loop deadline (decisions/standard-packs-everywhere.md, section 3).

The pack keeps an approved cleanup deadline and an observation watermark of its own. std-loop already has a
step's deadline, a dated sweep and the expiry of a step that did not finish in time (rules/quiet_round.dl).
Mapped onto them, the attempt is a step, `cleaned` its completion, the watermark the event time of the current
complete sweep, and `overdue` std-loop's deadline_expired.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
CLEANUP = REPO / "run" / "packs" / "cleanup-deadline"
STD_LOOP = REPO / "packs" / "std-loop"
OWN_SLOTS = {"deadline_us", "watermark_us"}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/standard-packs-everywhere.md, section 3. Waits until std-loop's LoopDeadline can name an "
    "absolute boundary (a decision of the loop track) and a planner has restated "
    "run/tests/test_cleanup_deadline.py through std-loop. Then import std-loop in "
    "run/packs/cleanup-deadline/pack.yaml, pinned to its sha256, and replace deadline_us and watermark_us by "
    "std-loop's deadline, sweep and deadline_expired."))
def test_cleanup_deadline_is_a_std_loop_deadline():
    manifest = yaml.safe_load((CLEANUP / "pack.yaml").read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest.get("imports") or ()}
    assert "std-loop" in by_name, "run/packs/cleanup-deadline/pack.yaml must import std-loop"
    entry = by_name["std-loop"]
    assert (CLEANUP / entry["path"]).resolve() == STD_LOOP.resolve(), "the import must point to packs/std-loop"
    assert re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))), "the import must pin a 64-hex sha256"

    slots = set()
    for path in sorted((CLEANUP / "schema").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for body in (doc.get("classes") or {}).values():
            slots |= set((body or {}).get("attributes") or {})
    assert not slots & OWN_SLOTS, f"cleanup-deadline still keeps its own deadline slots: {sorted(slots & OWN_SLOTS)}"

    from rezono_compiler import modules, pack, rules

    assert entry["sha256"] == modules.pack_hash(STD_LOOP), "the std-loop pin does not match packs/std-loop"
    derived = set(rules.load(pack.read(CLEANUP).rules).derived())
    assert "deadline_expired" in derived, "the overdue cleanup must be std-loop's deadline_expired"
