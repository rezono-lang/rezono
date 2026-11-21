"""Honest fact origins for examples/platform/facts/ (decisions/fact-origin-required.md).

Verifies that:
- core.sources.yaml marks invented synthetic rows (zones, synthetic releases) as `synthetic`,
  does not use a catch-all `git` default for invented rows, and does not duplicate default entries.
- Non-vendor demands in core.yaml carry a typed binding to a std-decision Decision record rather
  than merely pointing to any file under decisions/.
- Vendor evidence sidecars (keycloak_release, kubernetes_support, keycloak_release_source,
  postgres_transport_source) point to real vendor evidence/sources stating the values, never to
  acceptance/product-evidence.json or to a decision document that does not state the value.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from case_support import ROOT
from rezono_compiler import facts as compiler_facts, pack as compiler_pack, sources as compiler_sources

REPO = ROOT.parents[1]
FACTS = ROOT / "facts"
THIS_REPOSITORY = "rezono-lang/rezono"
DECISION = "decision"


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


def _is_test_or_acceptance_path(src: dict) -> bool:
    pos = str(src.get("position", "")).partition("#")[0].lower()
    name = str(src.get("name", "")).lower()
    return (
        "acceptance/" in pos
        or "product-evidence.json" in pos
        or "proof_cases/" in pos
        or "product-evidence.json" in name
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/fact-origin-required.md: examples/platform/facts/core.sources.yaml must "
        "mark synthetic rows (invented zones and releases with synthetic released_on_day ordinals) "
        "as synthetic, must not use a catch-all git default for invented rows, and must not "
        "duplicate default entries in records"
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

    # 3. Synthetic rows (invented zones and releases carrying synthetic released_on_day ordinals)
    # must resolve to kind `synthetic`, never `git`.
    model = compiler_pack.read(ROOT)
    core_data = yaml.safe_load(core_yaml.read_text(encoding="utf-8")) or {}
    entries = compiler_sources.file_entries(model, core_yaml, relative=Path("facts/core.yaml"))

    sources_by_record: dict[tuple[str, str], list[dict]] = {}
    for entry in entries:
        rel = entry["row"]["relation"]
        owner = rel.split("__", 1)[0]
        rec_id = json.loads(entry["row"]["key"])[0]
        sources_by_record.setdefault((owner, rec_id), []).extend(entry["sources"])

    bad_zones: dict[str, list[str]] = {}
    for zone in core_data.get("zone", []):
        kinds = sorted({s.get("kind") for s in sources_by_record.get(("zone", zone["id"]), []) if s.get("kind") != "pack"})
        if kinds != ["synthetic"]:
            bad_zones[zone["id"]] = kinds
    assert bad_zones == {}, f"invented zone rows in core.yaml must have synthetic origin, got: {bad_zones}"

    bad_releases: dict[str, list[str]] = {}
    for rel in core_data.get("release", []):
        if "released_on_day" in rel and isinstance(rel["released_on_day"], int):
            kinds = sorted({
                s.get("kind")
                for s in sources_by_record.get(("release", rel["id"]), [])
                if s.get("kind") != "pack"
            })
            if kinds != ["synthetic"]:
                bad_releases[rel["id"]] = kinds
    assert bad_releases == {}, (
        "release rows with synthetic released_on_day ordinals in core.yaml must have synthetic origin, "
        f"got: {bad_releases}"
    )


@pytest.mark.xfail(
    strict=True,
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/fact-origin-required.md: keycloak_release.sources.yaml, "
        "kubernetes_support.sources.yaml, keycloak_release_source.sources.yaml, and "
        "postgres_transport_source.sources.yaml must point to real vendor evidence/sources "
        "stating the recorded values, not to acceptance/product-evidence.json or silent decisions"
    ),
)
def test_vendor_evidence_sidecars_point_to_real_vendor_sources():
    model = compiler_pack.read(ROOT)

    # (stem, requires_external_vendor_source, required_values_if_citing_repo_file)
    targets = [
        ("keycloak_release_source", True, ("26.0.0", "2024-10-04")),
        ("postgres_transport_source", True, ("5432",)),
        ("keycloak_release", False, ("26.0.0", "2024-10-04")),
        ("kubernetes_support", False, ("1.32", "2026-02-28")),
    ]

    problems: list[str] = []
    for stem, require_external, required_values in targets:
        fact_path = FACTS / f"{stem}.yaml"
        sidecar_path = FACTS / f"{stem}.sources.yaml"
        assert fact_path.is_file(), f"missing {fact_path}"
        assert sidecar_path.is_file(), f"missing {sidecar_path}"

        entries = compiler_sources.file_entries(model, fact_path, relative=Path(f"facts/{stem}.yaml"))
        assert entries, f"expected rows in {fact_path.name}"

        non_pack_sources: list[dict] = []
        for entry in entries:
            non_pack = [s for s in entry["sources"] if s.get("kind") != "pack"]
            if not non_pack:
                problems.append(f"{sidecar_path.name}: row {entry['row']} has no non-pack source")
                continue
            non_pack_sources.extend(non_pack)

        for src in non_pack_sources:
            if _is_test_or_acceptance_path(src):
                problems.append(
                    f"{sidecar_path.name}: points to test/acceptance expectation file instead of "
                    f"vendor evidence ({src.get('position')!r})"
                )
                break

        if require_external:
            if not all(_is_external_vendor_source(src) for src in non_pack_sources):
                bad = [src for src in non_pack_sources if not _is_external_vendor_source(src)]
                problems.append(
                    f"{sidecar_path.name}: vendor source facts must cite an external vendor source "
                    f"(not repo git/test files), found: {bad[0]}"
                )
        else:
            for src in non_pack_sources:
                if _is_external_vendor_source(src):
                    continue
                if src.get("kind") == "git" and src.get("name") == THIS_REPOSITORY:
                    cited_rel = str(src.get("position", "")).partition("#")[0]
                    cited_file = REPO / cited_rel
                    if not cited_rel or not cited_file.is_file():
                        problems.append(f"{sidecar_path.name}: cited repo path {cited_rel!r} does not exist")
                        break
                    text = cited_file.read_text(encoding="utf-8")
                    missing_vals = [v for v in required_values if v not in text]
                    if missing_vals:
                        problems.append(
                            f"{sidecar_path.name}: cites {cited_rel!r}, which does not state the "
                            f"recorded vendor value(s) {missing_vals}"
                        )
                        break
                else:
                    problems.append(
                        f"{sidecar_path.name}: source is neither an external vendor source nor a "
                        f"repo document stating {required_values}: {src}"
                    )
                    break

    assert problems == [], "dishonest vendor evidence origins:\n- " + "\n- ".join(problems)
