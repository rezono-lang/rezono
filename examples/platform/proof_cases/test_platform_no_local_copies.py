"""Retire local copies beside standard packs and fix schema/rule duplication in examples/platform/.

Enforces decisions/standard-packs-everywhere.md:
- management_firewall.dl observation-comparison logic belongs in packs/std-loop.
- management_backup.dl uses std-decision Decision + std-time instead of a local BackupDecision.
- Retire duplicate VendorCycleSupport beside SeriesSupportSource and bind support_severity_drift
  properly rather than joining solely on (service, series).
- TlsRequirement carries an explicit `service` slot instead of abusing `id` as the service name.
"""

from __future__ import annotations

import pytest

from case_support import ROOT
from rezono_compiler import batch as compiler_batch, facts as compiler_facts, pack as compiler_pack, rules as compiler_rules

REPO = ROOT.parents[1]
STD_LOOP = REPO / "packs" / "std-loop"
STD_DECISION = REPO / "packs" / "std-decision"
STD_TIME = REPO / "packs" / "std-time"


def _load_pack(pack_dir):
    model = compiler_pack.read(pack_dir)
    assert model.rules is not None
    return model, compiler_rules.load(model.rules)


def _transitive_deps(program, relation: str) -> set[str]:
    seen: set[str] = set()
    derived = set(program.derived())
    stack = [relation]
    while stack:
        current = stack.pop()
        for dep in program.deps(current):
            if dep not in seen:
                seen.add(dep)
                if dep in derived:
                    stack.append(dep)
    return seen


def _closure(program, targets: tuple[str, ...]) -> set[str]:
    derived = set(program.derived())
    needed: set[str] = set()
    stack = list(targets)
    while stack:
        rel = stack.pop()
        if rel in needed or rel not in derived:
            continue
        needed.add(rel)
        stack.extend(dep for dep in program.deps(rel) if dep in derived and dep not in needed)
    return needed


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/standard-packs-everywhere.md: management_firewall.dl "
        "observation-comparison and sweep-completeness logic belongs in packs/std-loop "
        "rather than a local copy"
    ),
)
def test_management_firewall_uses_std_loop_comparison():
    _, loop_program = _load_pack(STD_LOOP)
    loop_derived = set(loop_program.derived())

    _, platform_program = _load_pack(ROOT)
    for target in ("managed_router_drift", "managed_router_unknown"):
        deps = _transitive_deps(platform_program, target)
        assert deps & loop_derived, (
            f"{target} does not consume any packs/std-loop comparison or sweep-completeness "
            f"relation; transitive deps={sorted(deps)}"
        )

    local_fw_rules = [r for r in platform_program.rules.values() if r.module == "management_firewall"]
    local_sweep_copy = [
        r.id for r in local_fw_rules
        for lit in r.body
        if lit.atom.relation == "router_sweep__complete"
    ]
    assert local_sweep_copy == [], (
        f"management_firewall.dl still re-implements local sweep-completeness logic in {local_sweep_copy} "
        "instead of using packs/std-loop"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/standard-packs-everywhere.md: management_backup.dl must use "
        "std-decision Decision and std-time instead of a local BackupDecision kind"
    ),
)
def test_management_backup_uses_std_decision_and_std_time():
    _, decision_program = _load_pack(STD_DECISION)
    _, time_program = _load_pack(STD_TIME)
    decision_derived = set(decision_program.derived())
    time_derived = set(time_program.derived())

    model, platform_program = _load_pack(ROOT)

    assert "backup_decision" not in model.kinds, (
        "local BackupDecision kind must be retired in favour of std-decision Decision + std-time"
    )

    backup_deps = _transitive_deps(platform_program, "managed_backup_state")
    assert backup_deps & decision_derived, (
        f"managed_backup_state does not consume any packs/std-decision relation; deps={sorted(backup_deps)}"
    )
    assert backup_deps & time_derived, (
        f"managed_backup_state does not consume any packs/std-time relation; deps={sorted(backup_deps)}"
    )

    local_backup_rules = [r for r in platform_program.rules.values() if r.module == "management_backup"]
    stale_reads = [
        (r.id, lit.atom.relation)
        for r in local_backup_rules
        for lit in r.body
        if lit.atom.relation.startswith("backup_decision")
    ]
    assert stale_reads == [], f"management_backup.dl still reads local backup_decision tables: {stale_reads}"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/standard-packs-everywhere.md: retire duplicate VendorCycleSupport beside "
        "SeriesSupportSource and bind support_severity_drift properly beyond (service, series)"
    ),
)
def test_retire_vendor_cycle_support_and_bind_support_drift():
    model, platform_program = _load_pack(ROOT)

    assert "vendor_cycle_support" not in model.kinds, (
        "duplicate VendorCycleSupport kind must be retired in favour of SeriesSupportSource"
    )
    assert "series_support_source" in model.kinds, "SeriesSupportSource must remain the canonical vendor support kind"

    for rel in ("support_severity", "latest_supported_cycle"):
        deps = _transitive_deps(platform_program, rel)
        assert any(dep.startswith("series_support_source") for dep in deps), (
            f"{rel} must read SeriesSupportSource; deps={sorted(deps)}"
        )
        assert not any(dep.startswith("vendor_cycle_support") for dep in deps), (
            f"{rel} still depends on retired vendor_cycle_support: {sorted(deps)}"
        )

    # SupportAssessmentEntry and support_severity_drift must bind to the evaluation reference /
    # cycle (not join solely on service + series, which cross-matches unrelated evaluation dates).
    entry_kind = model.kinds["support_assessment_entry"]
    loose_only_slots = {"id", "revision", "service", "series", "severity"}
    assert set(entry_kind.slots) - loose_only_slots, (
        "SupportAssessmentEntry must bind assessments beyond (service, series), e.g. to evaluation "
        f"reference/date/cycle; found only {sorted(entry_kind.slots)}"
    )

    drift_rules = [r for r in platform_program.rules.values() if r.head.relation == "support_severity_drift"]
    assert drift_rules, "expected compiled rules for support_severity_drift"
    for rule in drift_rules:
        entry_vars = {
            lit.atom.terms[0]
            for lit in rule.body
            if lit.atom.relation == "support_assessment_entry"
        }
        entry_lits = [
            lit for lit in rule.body
            if lit.atom.relation.startswith("support_assessment_entry__")
            and lit.atom.terms
            and lit.atom.terms[0] in entry_vars
        ]
        bound_slots = {lit.atom.relation.split("__", 1)[1] for lit in entry_lits}
        assert bound_slots - {"service", "series", "severity"}, (
            f"support_severity_drift ({rule.id}) binds support_assessment_entry only on "
            f"{sorted(bound_slots)}; it must bind drift to the evaluation reference or cycle"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/standard-packs-everywhere.md: TlsRequirement must carry an explicit "
        "service slot rather than abusing the requirement id as the service name"
    ),
)
def test_tls_requirement_has_explicit_service_slot():
    model, platform_program = _load_pack(ROOT)

    req_kind = model.kinds["tls_requirement"]
    assert "service" in req_kind.slots and req_kind.slots["service"].required, (
        f"TlsRequirement must declare a required `service` slot; slots={sorted(req_kind.slots)}"
    )

    for rel in ("managed_tls_finding", "managed_tls_unknown"):
        deps = _transitive_deps(platform_program, rel)
        assert "tls_requirement__service" in deps, (
            f"{rel} must read tls_requirement__service instead of equating requirement id with service"
        )

    # Behavioral proof: one service ('api') with two distinct caller-specific TlsRequirements
    # whose ids ('req-api-client-a', 'req-api-client-b') differ from the service name ('api').
    records = {
        "tls_requirement": [
            {"id": "req-api-client-a", "service": "api", "caller": "client-a",
             "name": "api.example.org", "transport": "tls"},
            {"id": "req-api-client-b", "service": "api", "caller": "client-b",
             "name": "api.example.org", "transport": "tls"},
        ],
        "tls_clock": [{"id": "policy", "day": "2026-06-10", "warning_days": 7}],
        "tls_root": [
            {"id": "trust-a", "caller": "client-a", "authority": "root-a"},
            {"id": "trust-b", "caller": "client-b", "authority": "root-b"},
        ],
        "tls_issuer": [{"id": "intermediate-a", "issuer": "root-a"}],
        "tls_read": [{"id": "read-api", "service": "api", "complete": True}],
        "tls_leaf": [{
            "id": "leaf-api", "service": "api", "read": "read-api",
            "dns_name": "api.example.org", "issuer": "intermediate-a",
            "begins": "2026-06-01", "ends": "2026-09-01",
        }],
    }
    base_rows = compiler_facts.rows_of(model, records)
    targets = ("managed_tls_finding", "managed_tls_unknown")
    with compiler_batch.connect(platform_program, base_rows) as con:
        compiler_batch.compute(con, platform_program, relations=_closure(platform_program, targets))
        out = compiler_batch.read(con, platform_program, targets)

    assert out["managed_tls_unknown"] == set(), f"unexpected unknown TLS rows: {out['managed_tls_unknown']}"
    findings = out["managed_tls_finding"]
    assert any(row[-1] == "untrusted-chain" for row in findings), (
        f"client-b must receive an untrusted-chain finding for service 'api'; got {findings}"
    )
    assert not any(row[-1] == "missing" for row in findings), (
        f"service 'api' has a presented leaf and must not report 'missing'; got {findings}"
    )
