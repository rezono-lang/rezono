"""Honest fact origins for examples/platform/facts/core.yaml (decisions/fact-origin-required.md).

Verifies that:
- core.sources.yaml drops the catch-all `git` default for invented rows, removes duplicate
  records repeating `default`, and marks invented synthetic releases (such as `keycloak-27rc`
  and releases carrying synthetic placeholder `released_on_day` ordinals 1/50/100/150/200/250)
  as `synthetic` while allowing honest decision provenance for platform design choices and real
  vendor provenance for real releases (decisions/platform-facts-not-conclusions.md §1 #6 & §4).
- Non-vendor demands in core.yaml carry a typed binding to a std-decision Decision record rather
  than merely pointing to any file under decisions/.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from case_support import ROOT
from rezono_compiler import facts as compiler_facts, pack as compiler_pack, sources as compiler_sources

FACTS = ROOT / "facts"
THIS_REPOSITORY = "rezono-lang/rezono"
DECISION = "decision"
PLACEHOLDER_RELEASE_DAYS = frozenset({1, 50, 100, 150, 200, 250})


def _strip_of(entry: dict) -> dict:
    return {k: v for k, v in entry.items() if k != "of"}


def _is_external_vendor_source(src: dict) -> bool:
    kind = src.get("kind")
    url = str(src.get("url", ""))
    if kind in ("document", "tool"):
        return url.startswith("https://") and THIS_REPOSITORY not in url
    if kind == "git":
        name = src.get("name")
        return bool(name) and name != THIS_REPOSITORY
    return False


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/fact-origin-required.md: examples/platform/facts/core.sources.yaml must "
        "not use a catch-all git default for invented rows, must not duplicate default entries in "
        "records, and must mark invented synthetic releases with placeholder released_on_day "
        "ordinals as synthetic"
    ),
)
def test_core_sources_marks_synthetic_rows_without_catchall_git_default_or_duplicates():
    core_yaml = FACTS / "core.yaml"
    core_sources_yaml = FACTS / "core.sources.yaml"

    sidecar = yaml.safe_load(core_sources_yaml.read_text(encoding="utf-8")) or {}
    default = sidecar.get("default")
    records = sidecar.get("records") or []

    # 1. No catch-all git default giving blanket git provenance to invented rows.
    assert not (isinstance(default, dict) and default.get("kind") == "git"), (
        f"core.sources.yaml uses a catch-all git default giving invented rows git provenance: {default}"
    )

    # 2. No record entries repeating the default verbatim.
    if isinstance(default, dict):
        duplicates = [rec.get("of") for rec in records if _strip_of(rec) == default]
        assert duplicates == [], (
            f"core.sources.yaml has {len(duplicates)} duplicate record entries repeating default: {duplicates}"
        )

    # 3. Invented synthetic releases (keycloak-27rc and any release carrying placeholder
    # released_on_day ordinals 1/50/100/150/200/250 without real vendor publication provenance)
    # must be marked `synthetic`, never repo-internal `git`.
    model = compiler_pack.read(ROOT)
    core_data = yaml.safe_load(core_yaml.read_text(encoding="utf-8")) or {}
    entries = compiler_sources.file_entries(model, core_yaml, relative=Path("facts/core.yaml"))

    sources_by_record: dict[tuple[str, str], list[dict]] = {}
    for entry in entries:
        rel = entry["row"]["relation"]
        owner = rel.split("__", 1)[0]
        rec_id = json.loads(entry["row"]["key"])[0]
        sources_by_record.setdefault((owner, rec_id), []).extend(entry["sources"])

    bad_releases: dict[str, list[dict]] = {}
    for rel in core_data.get("release", []):
        rel_id = rel["id"]
        non_pack = [s for s in sources_by_record.get(("release", rel_id), []) if s.get("kind") != "pack"]
        if rel_id == "keycloak-27rc":
            if not non_pack or any(s.get("kind") != "synthetic" for s in non_pack):
                bad_releases[rel_id] = non_pack
        elif rel.get("released_on_day") in PLACEHOLDER_RELEASE_DAYS:
            # Placeholder ordinals are invented unless backed by an external vendor source;
            # they must never carry repo-internal git provenance.
            if not non_pack or not all(
                s.get("kind") == "synthetic" or _is_external_vendor_source(s) for s in non_pack
            ):
                bad_releases[rel_id] = non_pack

    assert bad_releases == {}, (
        "invented release rows with placeholder released_on_day ordinals in core.yaml must carry "
        f"synthetic (or external vendor) provenance, not repo-internal git: {bad_releases}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "extra: decisions/fact-origin-required.md: platform-designed demands in "
        "examples/platform/facts/core.yaml must be bound by a typed arrow to a std-decision "
        "Decision record rather than merely citing an existing file under decisions/"
    ),
)
def test_core_demands_have_typed_decision_bindings():
    model = compiler_pack.read(ROOT)
    core_yaml = FACTS / "core.yaml"
    core_data = yaml.safe_load(core_yaml.read_text(encoding="utf-8")) or {}
    demands = {row["id"]: row for row in core_data.get("demand", [])}
    assert demands, "expected demand rows in examples/platform/facts/core.yaml"

    # Identify demands already grounded directly in external vendor documentation.
    demand_sources: dict[str, list[dict]] = {}
    for entry in compiler_sources.file_entries(model, core_yaml, relative=Path("facts/core.yaml")):
        rel = entry["row"]["relation"]
        if rel.split("__", 1)[0] == "demand":
            rec_id = json.loads(entry["row"]["key"])[0]
            demand_sources.setdefault(rec_id, []).extend(entry["sources"])

    non_vendor_demands = sorted(
        ident for ident in demands
        if not any(_is_external_vendor_source(src) for src in demand_sources.get(ident, []))
    )
    assert non_vendor_demands, "expected platform-designed (non-vendor) demands in core.yaml"

    # Load all authored facts to inspect std-decision records and typed arrows to Decision.
    all_rows: dict[str, list[tuple[str, ...]]] = {}
    for path in sorted(FACTS.glob("*.yaml")):
        if path.name.endswith(".sources.yaml"):
            continue
        for rel, tuples in compiler_facts.load(model, path).items():
            all_rows.setdefault(rel, []).extend(tuples)

    decision_kinds = {k for k in model.kinds if DECISION in model.ancestors(k)}
    authored_decisions = (
        {row[0] for row in all_rows.get(f"{DECISION}__decider", [])}
        & {row[0] for row in all_rows.get(f"{DECISION}__decided_on", [])}
    )

    bound_demands: set[str] = set()

    # Case A: Demand itself has an arrow to Decision (or a subkind of Decision).
    demand_kind = model.kinds["demand"]
    for slot in demand_kind.slots.values():
        if slot.arrow and slot.range in decision_kinds:
            for rec_id, target_decision in all_rows.get(slot.table, []):
                if target_decision in authored_decisions:
                    bound_demands.add(rec_id)

    # Case B: A separate binding kind has both an arrow to Demand and an arrow to Decision.
    for kind in model.kinds.values():
        demand_slots = [s for s in kind.slots.values() if s.arrow and s.range == "demand"]
        decision_slots = [s for s in kind.slots.values() if s.arrow and s.range in decision_kinds]
        if not (demand_slots and decision_slots):
            continue
        for d_slot in demand_slots:
            by_binding = {row[0]: row[1] for row in all_rows.get(d_slot.table, [])}
            for dec_slot in decision_slots:
                for binding_id, target_decision in all_rows.get(dec_slot.table, []):
                    if binding_id in by_binding and target_decision in authored_decisions:
                        bound_demands.add(by_binding[binding_id])

    unbound = sorted(set(non_vendor_demands) - bound_demands)
    assert unbound == [], (
        f"{len(unbound)} of {len(non_vendor_demands)} platform-designed demands lack a typed binding "
        f"to an authored std-decision Decision record: {unbound}"
    )
