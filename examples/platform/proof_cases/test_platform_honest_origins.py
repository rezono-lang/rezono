"""Honest fact origins for examples/platform/facts/core.yaml (decisions/fact-origin-required.md).

Verifies that examples/platform/facts/core.sources.yaml drops the catch-all `git` default for a
mixed fact file (design choices, vendor facts, and synthetic fixtures) and removes duplicate
record entries repeating `default` verbatim or targeting the same record twice.
"""

from __future__ import annotations

import pytest
import yaml

from case_support import ROOT

FACTS = ROOT / "facts"


def _strip_of(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "of"}


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/fact-origin-required.md: examples/platform/facts/core.sources.yaml must "
        "not use a catch-all git default for a mixed fact file and must not repeat default entries "
        "verbatim or duplicate record selectors in records"
    ),
)
def test_core_sources_has_no_catchall_git_default_or_duplicates():
    core_sources_yaml = FACTS / "core.sources.yaml"

    sidecar = yaml.safe_load(core_sources_yaml.read_text(encoding="utf-8")) or {}
    default = sidecar.get("default")
    records = sidecar.get("records") or []

    # 1. No catch-all git default giving blanket git provenance to every row of mixed core.yaml.
    assert not (isinstance(default, dict) and default.get("kind") == "git"), (
        f"core.sources.yaml uses a catch-all git default giving blanket git provenance: {default}"
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
