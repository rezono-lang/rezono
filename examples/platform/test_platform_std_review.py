"""The platform assesses its reviews with std-review (decisions/standard-packs-everywhere.md, section 3).

std-review was imported by no pack. Scene 2 of the platform has review as a required area, and the platform
already imports std-access at the pin std-review uses, so the platform is its first consumer. The relation
names are those of decisions/review-and-rights.md.
"""

import re
from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parent
REPO = PLATFORM.parents[1]
STD_REVIEW = REPO / "packs" / "std-review"
STD_REVIEW_RELATIONS = frozenset({
    "review_active", "review_current", "review_valid", "change_accepted", "change_rejected", "change_stale",
    "change_proposed", "review_due",
})
_DECL = re.compile(r"^\s*\.decl\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", re.M)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/standard-packs-everywhere.md, section 3. Import std-review in examples/platform/pack.yaml, "
    "pinned to its sha256, beside std-access, so the compiled platform pack carries std-review's relations. "
    "Reading the tenant connection reviews as std-review reviews is a later step with its own decision."))
def test_platform_imports_std_review():
    manifest = yaml.safe_load((PLATFORM / "pack.yaml").read_text(encoding="utf-8"))
    by_name = {entry["name"]: entry for entry in manifest.get("imports") or ()}
    assert "std-review" in by_name, "examples/platform/pack.yaml must import std-review"
    entry = by_name["std-review"]
    assert (PLATFORM / entry["path"]).resolve() == STD_REVIEW.resolve(), "the import must point to packs/std-review"
    assert re.fullmatch(r"[0-9a-f]{64}", str(entry.get("sha256", ""))), "the import must pin a 64-hex sha256"

    redeclared = sorted(f"{path.name}:{name}" for path in sorted((PLATFORM / "rules").glob("*.dl"))
                        for name in _DECL.findall(path.read_text(encoding="utf-8")) if name in STD_REVIEW_RELATIONS)
    assert not redeclared, f"Platform rules must not rebuild std-review relations: {redeclared}"

    from rezono_compiler import modules, pack, rules

    assert entry["sha256"] == modules.pack_hash(STD_REVIEW), "the std-review pin does not match packs/std-review"
    derived = set(rules.load(pack.read(PLATFORM).rules).derived())
    assert STD_REVIEW_RELATIONS <= derived, f"Missing std-review relations: {sorted(STD_REVIEW_RELATIONS - derived)}"
