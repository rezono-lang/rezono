"""Every fact row in build/facts/roles.yaml must carry an honest fact origin via
build/facts/roles.sources.yaml (decisions/fact-origin-required.md §§1-3).
"""

from __future__ import annotations

from pathlib import Path
import re

import pytest

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "build"
ROLES_YAML = BUILD / "facts" / "roles.yaml"
ROLES_SOURCES = BUILD / "facts" / "roles.sources.yaml"

DISALLOWED_KINDS = frozenset({"pack", "scenario", "synthetic"})
SHA_40 = re.compile(r"^[0-9a-f]{40}$")


def _is_self_citing_git(src: dict) -> bool:
    if src.get("kind") != "git":
        return False
    pos = str(src.get("position", "")).partition("#")[0].partition(":")[0]
    if not pos:
        return False
    target = ROLES_YAML.resolve()
    return (ROOT / pos).resolve() == target or (BUILD / pos).resolve() == target


def _is_honest_origin(src: dict) -> bool:
    kind = src.get("kind")
    if kind in DISALLOWED_KINDS or not isinstance(kind, str) or not kind:
        return False
    if _is_self_citing_git(src):
        return False
    if kind == "git":
        rev = str(src.get("revision", ""))
        if not SHA_40.fullmatch(rev):
            return False
        if src.get("name") == "rezono-lang/rezono":
            cited_path = str(src.get("position", "")).partition("#")[0].partition(":")[0]
            if not cited_path or not (ROOT / cited_path).is_file():
                return False
    return True


def test_build_roles_fact_file_has_honest_origins():
    from rezono_compiler import facts, pack, sources

    assert ROLES_YAML.is_file(), "build/facts/roles.yaml is missing"
    assert ROLES_SOURCES.is_file(), (
        "build/facts/roles.sources.yaml is missing; every row of build/facts/roles.yaml requires an origin"
    )

    model = pack.read(BUILD)
    entries = sources.file_entries(model, ROLES_YAML, relative=Path("facts/roles.yaml"))
    expected_rows = sum(len(rows) for rows in facts.load(model, ROLES_YAML).values())
    assert expected_rows > 0, "expected rows in build/facts/roles.yaml"
    assert len(entries) == expected_rows, (
        f"roles.sources.yaml must cover all {expected_rows} base rows of build/facts/roles.yaml, got {len(entries)}"
    )

    missing = sources.missing_origins(model, entries, BUILD)
    assert missing == [], (
        f"build/facts/roles.yaml still has {sources.missing_origin_count(missing)} rows without origin: {missing}"
    )

    bad_entries = [
        entry
        for entry in entries
        if not any(_is_honest_origin(src) for src in entry.get("sources", ()))
    ]
    assert bad_entries == [], (
        "every row of build/facts/roles.yaml must have at least one honest non-default, non-synthetic origin: "
        f"{bad_entries}"
    )
