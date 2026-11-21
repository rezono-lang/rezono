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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/fact-origin-required.md: examples/platform/facts/core.sources.yaml must "
        "keep an honest default (never pack/scenario/synthetic or self-citing facts/core.yaml, and "
        "for kind='git' citing an existing decisions/*.md file) and must not repeat default "
        "entries verbatim or duplicate record selectors in records"
    ),
)
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
