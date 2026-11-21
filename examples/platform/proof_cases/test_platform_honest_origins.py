"""Honest fact origins for examples/platform/facts/core.yaml (decisions/fact-origin-required.md).

Verifies that examples/platform/facts/core.sources.yaml:
- uses an honest default (never `pack`, `scenario`, `synthetic`, or self-citing `facts/core.yaml`;
  and when `kind: git`, pointing to an existing `decisions/*.md` file in this repository), and
- removes duplicate record entries repeating `default` verbatim or targeting the same record twice.
"""

from __future__ import annotations

import pytest
import yaml

from case_support import ROOT

REPO = ROOT.parents[1]
FACTS = ROOT / "facts"
FORBIDDEN_DEFAULT_KINDS = frozenset({"pack", "scenario", "synthetic"})


def _strip_of(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "of"}


def test_core_sources_has_honest_default_without_duplicate_records():
    core_sources_yaml = FACTS / "core.sources.yaml"

    sidecar = yaml.safe_load(core_sources_yaml.read_text(encoding="utf-8")) or {}
    default = sidecar.get("default")
    records = sidecar.get("records") or []

    # 1. Honest default: no pack/scenario/synthetic, no self-citing facts/core.yaml,
    #    and when kind == "git", must cite an existing decisions/*.md file.
    if isinstance(default, dict):
        kind = default.get("kind")
        assert kind not in FORBIDDEN_DEFAULT_KINDS, (
            f"core.sources.yaml default uses forbidden kind {kind!r}: {default}"
        )
        pos_path = str(default.get("position", "")).partition("#")[0]
        assert pos_path not in {"facts/core.yaml", "examples/platform/facts/core.yaml"}, (
            f"core.sources.yaml default self-cites facts/core.yaml: {default}"
        )
        if kind == "git":
            assert pos_path.startswith("decisions/") and pos_path.endswith(".md") and (REPO / pos_path).is_file(), (
                f"core.sources.yaml git default must cite an existing decisions/*.md file: {default}"
            )

    # 2. No record entries repeating default verbatim.
    if isinstance(default, dict):
        duplicates = [rec.get("of") for rec in records if _strip_of(rec) == default]
        assert duplicates == [], (
            f"core.sources.yaml has {len(duplicates)} duplicate record entries repeating default: {duplicates}"
        )

    # 3. No duplicate record selectors in records.
    seen: set[tuple[str, str, str | None]] = set()
    repeated_selectors: list[dict] = []
    for rec in records:
        of = rec.get("of") or {}
        key = (str(of.get("kind", "")), str(of.get("id", "")), of.get("slot"))
        if key in seen:
            repeated_selectors.append(of)
        seen.add(key)
    assert repeated_selectors == [], (
        f"core.sources.yaml has duplicate record selectors in records: {repeated_selectors}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/fact-origin-required.md: PlatformStartupTarget rows in "
        "examples/platform/facts/standard-order.yaml must carry kind: synthetic in "
        "standard-order.sources.yaml (or be supplied from a test fixture instead of "
        "standard-order.yaml) rather than citing decisions/safe-step-rounds.md#4 as a "
        "non-synthetic git source."
    ),
)
def test_platform_startup_target_has_honest_synthetic_or_fixture_origin():
    from rezono_compiler import pack as compiler_pack, sources as compiler_sources

    standard_order_data = yaml.safe_load((FACTS / "standard-order.yaml").read_text(encoding="utf-8")) or {}
    startup_targets = standard_order_data.get("platform_startup_target") or []

    model = compiler_pack.read(ROOT)
    entries = compiler_sources.read(model, ROOT)
    startup_entries = [
        entry
        for entry in entries
        if entry["row"]["relation"] == "platform_startup_target"
        or entry["row"]["relation"].startswith("platform_startup_target__")
    ]

    if not startup_targets and not startup_entries:
        return

    assert startup_entries, "expected resolved compiler source entries for PlatformStartupTarget rows"
    dishonest: list[tuple[dict, list[dict]]] = []
    for entry in startup_entries:
        explicit = [src for src in entry["sources"] if src.get("kind") != "pack"]
        has_synthetic = any(
            src.get("kind") == "synthetic"
            and bool(str(src.get("name", "")).strip())
            and bool(str(src.get("position", "")).strip())
            for src in explicit
        )
        non_synthetic = [src for src in explicit if src.get("kind") != "synthetic"]
        if not has_synthetic or non_synthetic:
            dishonest.append((entry["row"], explicit))

    assert dishonest == [], (
        "PlatformStartupTarget rows in examples/platform/facts/ must carry honest kind: synthetic "
        "origins (or be supplied from a test fixture) rather than citing a decision section as a "
        f"non-synthetic source: {dishonest[:3]}"
    )
