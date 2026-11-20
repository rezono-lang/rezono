"""A dispatch approval is a std-decision decision (decisions/standard-packs-everywhere.md, section 3).

The pack keeps an approval with its own outcome and an expiry in microseconds. std-decision has the decision
record: who decided, from when and until when it applies, and whether it is in force. Mapped onto it, an
approval is a kind of the pack that is a Decision, the approver its decider and the expiry its validity; the
plan hash, currency, cap and outcome stay the approval's own slots.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
DISPATCH = REPO / "run" / "packs" / "dispatch"
STD_DECISION = REPO / "packs" / "std-decision"


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/standard-packs-everywhere.md, section 3. Waits until std-decision can bound a decision's "
    "validity at an instant (a decision of the language track) and a planner has restated "
    "run/tests/test_dispatch_policy.py and the offline replay case in run/fixtures/offline/. Then import "
    "std-decision in run/packs/dispatch/pack.yaml, pinned to its sha256, make the approval a kind that is a "
    "Decision, and replace expires_us by the decision's validity."))
def test_dispatch_approval_is_a_std_decision():
    manifest = yaml.safe_load((DISPATCH / "pack.yaml").read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest.get("imports") or ()}
    assert "std-decision" in by_name, "run/packs/dispatch/pack.yaml must import std-decision"
    entry = by_name["std-decision"]
    assert (DISPATCH / entry["path"]).resolve() == STD_DECISION.resolve(), "the import must point to packs/std-decision"
    assert re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))), "the import must pin a 64-hex sha256"

    classes = {}
    for path in sorted((DISPATCH / "schema").glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        classes.update({name: body or {} for name, body in (doc.get("classes") or {}).items()})
    decisions = sorted(name for name, body in classes.items() if body.get("is_a") == "Decision")
    assert decisions, "a dispatch approval must be a kind that is a std-decision Decision"
    expiring = sorted(name for name, body in classes.items() if "expires_us" in (body.get("attributes") or {}))
    assert not expiring, f"the expiry is the decision's validity, not a slot of its own: {expiring}"

    from rezono_compiler import modules, pack, rules

    assert entry["sha256"] == modules.pack_hash(STD_DECISION), "the std-decision pin does not match packs/std-decision"
    derived = set(rules.load(pack.read(DISPATCH).rules).derived())
    assert "in_force_on" in derived, "the dispatch pack must carry std-decision's rules"
