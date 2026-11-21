"""Honest fact origins for examples/platform/facts/core.yaml (decisions/fact-origin-required.md,
decisions/platform-facts-not-conclusions.md section 4).

Verifies that examples/platform/facts/core.sources.yaml:
- marks `keycloak-27rc` (the invented `stable: 'no'` release) with a `synthetic` origin citing
  `decisions/platform-facts-not-conclusions.md` (with no day-number assumptions),
- uses an honest default (never `pack`, `scenario`, `synthetic`, or self-citing `facts/core.yaml`;
  and when `kind: git`, pointing to an existing `decisions/*.md` file in this repository), and
- removes duplicate record entries repeating `default` verbatim or targeting the same record twice.
"""

from __future__ import annotations

import json
import re

import yaml

from case_support import ROOT
from rezono_compiler import pack as compiler_pack, sources as compiler_sources

REPO = ROOT.parents[1]
FACTS = ROOT / "facts"
FORBIDDEN_DEFAULT_KINDS = frozenset({"pack", "scenario", "synthetic"})


def _strip_of(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "of"}


def test_keycloak_27rc_has_synthetic_origin():
    """decisions/platform-facts-not-conclusions.md section 4: keycloak-27rc has a synthetic origin."""
    core = yaml.safe_load((FACTS / "core.yaml").read_text(encoding="utf-8")) or {}
    releases = {row["id"]: row for row in core.get("release", [])}
    assert "keycloak-27rc" in releases, "keycloak-27rc release is missing from examples/platform/facts/core.yaml"
    assert str(releases["keycloak-27rc"].get("stable")) == "no", releases["keycloak-27rc"]

    sidecar = yaml.safe_load((FACTS / "core.sources.yaml").read_text(encoding="utf-8")) or {}
    matching = [
        rec
        for rec in sidecar.get("records") or []
        if (rec.get("of") or {}).get("kind") == "release" and (rec.get("of") or {}).get("id") == "keycloak-27rc"
    ]
    assert len(matching) == 1, f"expected one core.sources.yaml entry for release keycloak-27rc, got {matching}"
    entry = matching[0]
    assert entry.get("kind") == "synthetic", f"keycloak-27rc must have kind='synthetic', got {entry}"
    assert "platform-facts-not-conclusions.md" in str(entry.get("name", "")), (
        f"keycloak-27rc synthetic origin must cite decisions/platform-facts-not-conclusions.md: {entry}"
    )

    model = compiler_pack.read(ROOT)
    resolved = [
        item
        for item in compiler_sources.file_entries(model, FACTS / "core.yaml")
        if item["row"]["relation"].split("__")[0] == "release"
        and json.loads(item["row"]["key"])[0] == "keycloak-27rc"
    ]
    assert resolved, "compiler_sources.file_entries produced no entries for release keycloak-27rc"
    for item in resolved:
        kinds = {src.get("kind") for src in item["sources"]}
        assert kinds == {"synthetic"}, f"resolved origins for keycloak-27rc must be strictly synthetic: {item}"


def test_core_sources_has_honest_default_without_duplicate_records():
    core_sources_yaml = FACTS / "core.sources.yaml"

    sidecar = yaml.safe_load(core_sources_yaml.read_text(encoding="utf-8")) or {}
    default = sidecar.get("default")
    records = sidecar.get("records") or []

    # 1. Honest default: must exist as a mapping with a 40-hex revision, no pack/scenario/synthetic,
    #    no self-citing facts/core.yaml, and when kind == "git", must cite an existing decisions/*.md file.
    assert isinstance(default, dict), f"core.sources.yaml must define a mapping default: {default!r}"
    assert re.fullmatch(r"[0-9a-f]{40}", str(default.get("revision", ""))), (
        f"core.sources.yaml default must carry a 40-hex revision: {default}"
    )
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
