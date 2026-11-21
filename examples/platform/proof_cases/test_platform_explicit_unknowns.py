"""Explicit unknown outcomes and single-source connection classification in platform rules.

Covers four silent-drop / duplication defects in examples/platform/rules/:
- dependency_gaps.dl silently drops consumers whose provider is ambiguous.
- support_version_policy.dl computes latest_supported_cycle without a completeness proof
  and silently drops conflicting vendor cycles.
- admission_assumption.dl silently drops eligible requests once step >= 32.
- admission_assumption.dl duplicates connection classification from tenant_connection_review.dl.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest

from case_support import ROOT, verified
from rezono_compiler import batch as compiler_batch, facts as compiler_facts, pack as compiler_pack, rules as compiler_rules

NO = "no"
REF = "spring-check"


def _transitive_deps(program, relation: str) -> set[str]:
    seen: set[str] = set()
    stack = [relation]
    while stack:
        current = stack.pop()
        for dep in program.deps(current):
            if dep not in seen:
                seen.add(dep)
                if dep in program.derived():
                    stack.append(dep)
    return seen


def _ambiguous_provider_records() -> dict[str, list[dict]]:
    function = lambda key: {"id": key, "recovery_allowed": NO, "open_by_design": NO}
    service = lambda key, product: {"id": key, "product": product, "role": "app-role", "step": 1}
    return {
        "zone": [{"id": "inner", "outside": NO, "entry_boundary": NO, "isolated_recovery": NO, "workload": "yes"}],
        "cluster_class": [{"id": "shared"}],
        "platform_role": [{"id": "app-role", "zone": "inner", "cluster_class": "shared", "runs_images": "yes",
                           "build_authority": NO}],
        "function": [function("login")],
        "product": [{"id": "shop-app"}, {"id": "idp-app"}],
        "offer": [{"id": "o-login", "product": "idp-app", "function": "login", "port": 443}],
        "demand": [{"id": "d-login", "product": "shop-app", "function": "login"}],
        # Two services offer login, with no Choice record selecting between them.
        "service": [service("shop", "shop-app"), service("idp-a", "idp-app"), service("idp-b", "idp-app")],
        "cluster_role": [{"id": "worker-role", "control_placement": "local"}],
        "cluster": [{"id": "east", "role": "worker-role"}, {"id": "west", "role": "worker-role"}],
        "cluster_service_binding": [
            {"id": "b-shop", "service": "shop", "cluster": "east"},
            {"id": "b-idp-a", "service": "idp-a", "cluster": "east"},
            {"id": "b-idp-b", "service": "idp-b", "cluster": "west"},
        ],
        "failure_domain_membership": [
            {"id": "m-east", "cluster": "east", "domain": "room-a"},
            {"id": "m-west", "cluster": "west", "domain": "room-b"},
        ],
        "function_inventory_receipt": [{"id": "r-login", "function": "login"}],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/platform-five-scenes.md: dependency_gaps.dl must emit an explicit "
        "dependency_gap or dependency_gap_unknown finding when a consumer has an ambiguous_provider, "
        "rather than silently emitting neither"
    ),
)
def test_ambiguous_provider_produces_explicit_gap_or_unknown():
    from management_probes import compiled

    data = _ambiguous_provider_records()
    model, state = compiled(data)

    assert ("shop", "login") in state.derived.get("ambiguous_provider", set())

    findings = [
        (rel, row)
        for rel in ("dependency_gap", "dependency_gap_unknown")
        for row in state.derived.get(rel, set())
        if len(row) >= 3 and row[:2] == ("shop", "login") and row[2]
    ]
    assert findings, (
        "consumer 'shop' has an ambiguous_provider for 'login', yet both dependency_gap and "
        "dependency_gap_unknown emitted nothing for ('shop', 'login')"
    )
    for rel, row in findings:
        leaves = verified(rel, row, state=(model, state))
        assert any(r == "demand__function" and k[0] == "d-login" for r, k in leaves)

    # Control: once an explicit Choice selects idp-a, ambiguity and its finding disappear.
    resolved = copy.deepcopy(data)
    resolved["choice"] = [{"id": "c-shop-login", "service": "shop", "function": "login", "provider": "idp-a"}]
    _, resolved_state = compiled(resolved)
    assert ("shop", "login") not in resolved_state.derived.get("ambiguous_provider", set())
    for rel, row in findings:
        assert row not in resolved_state.derived.get(rel, set())


def _support_decision(key: str) -> dict:
    return {
        "id": key, "title": key, "state": "in_force", "decider": ["platform-board"],
        "valid_from": "2026-01-01", "valid_from_day": 20260101,
    }


def _support_cycle(key: str, series: str, start: int, end: int) -> dict:
    return {
        "id": key, "on_axis": "support-days", "start": start, "end": end, "product": "kp", "series": series,
        "source_url": f"https://vendor.example.org/support/{series}",
        "source_sha256": format(start * 1000 + end, "064x"),
    }


def _support_records(cycles: list[dict]) -> dict[str, list[dict]]:
    return {
        "zone": [{"id": "inner", "outside": NO, "entry_boundary": NO, "isolated_recovery": NO, "workload": "yes"}],
        "cluster_class": [{"id": "shared"}],
        "platform_role": [{"id": "app-role", "zone": "inner", "cluster_class": "shared", "runs_images": "yes",
                           "build_authority": NO}],
        "product": [{"id": "kp"}],
        "service": [{"id": "svc", "product": "kp", "role": "app-role", "step": 1}],
        "release": [{"id": "kp-1.9.3", "product": "kp", "released_on_day": 1, "stable": "yes",
                     "version": "1.9.3", "series": "1.9"}],
        "pin": [{"id": "pin-svc", "service": "svc", "release": "kp-1.9.3"}],
        "axis": [{"id": "support-days"}],
        "vendor_cycle_support": cycles,
        "reference_point": [{"id": "day-300", "on_axis": "support-days", "position": 300, "horizon": 0}],
        "reference_date": [{"id": "march", "title": "march", "date": "2026-03-01", "day": 20260301}],
        "support_reference": [{"id": REF, "point": "day-300", "standing_on": "march"}],
        "decision": [_support_decision("policy-30")],
        "support_policy": [{"id": "sp-30", "decision": "policy-30", "product": "kp", "warning_days": 30}],
    }


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/platform-five-scenes.md: support_version_policy.dl must require a "
        "completeness proof for a product's vendor cycle list before deriving latest_supported_cycle, "
        "and report an explicit unknown finding when cycle-list completeness is absent"
    ),
)
def test_latest_supported_cycle_requires_completeness_proof():
    from management_probes import compiled

    # No completeness receipt is supplied for product 'kp's vendor cycle inventory.
    data = _support_records([
        _support_cycle("kp-1.9", "1.9", 100, 320),
        _support_cycle("kp-1.10", "1.10", 200, 500),
    ])
    model, state = compiled(data)
    program = compiler_rules.load(model.rules)

    latest = {row for row in state.derived.get("latest_supported_cycle", set()) if row[:2] == (REF, "kp")}
    assert latest == set(), (
        f"latest_supported_cycle claimed {latest} without any completeness proof for product 'kp's cycle list"
    )

    output_rels = [name for name, rel in program.relations.items() if rel.role == "derived" and rel.explain is not None]
    unknown_hits = [
        (rel, row)
        for rel in output_rels
        if "unknown" in rel
        for row in state.derived.get(rel, set())
        if len(row) >= 3 and row[0] == REF and row[1] == "kp" and row[-1]
    ]
    assert unknown_hits, (
        "missing completeness proof for product 'kp's cycle list must produce an explicit unknown output row"
    )

    deps = _transitive_deps(program, "latest_supported_cycle")
    completeness_tokens = ("complete", "receipt", "inventory", "sweep")
    assert any(any(tok in dep for tok in completeness_tokens) for dep in deps), (
        f"latest_supported_cycle does not depend on any completeness/inventory receipt relation: {sorted(deps)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/platform-five-scenes.md: support_version_policy.dl must emit an explicit "
        "unknown or conflict finding when conflicting vendor cycle statements affect "
        "latest_supported_cycle, rather than silently dropping the conflicting cycle"
    ),
)
def test_latest_supported_cycle_conflict_produces_explicit_unknown():
    from management_probes import compiled

    # svc is pinned to 1.9, while the newer 1.10 series has two disagreeing vendor statements.
    data = _support_records([
        _support_cycle("kp-1.9", "1.9", 100, 320),
        _support_cycle("kp-1.10-a", "1.10", 200, 500),
        _support_cycle("kp-1.10-b", "1.10", 200, 600),
    ])
    model, state = compiled(data)
    program = compiler_rules.load(model.rules)

    assert ("kp", "1.10") in state.derived.get("vendor_cycle_disagreement", set())

    latest = {row for row in state.derived.get("latest_supported_cycle", set()) if row[:2] == (REF, "kp")}
    assert latest == set(), (
        f"conflicting 1.10 cycle statements silently disappeared and let latest_supported_cycle fall back to {latest}"
    )

    output_rels = [name for name, rel in program.relations.items() if rel.role == "derived" and rel.explain is not None]
    conflict_outputs = [
        (rel, row)
        for rel in output_rels
        if any(tok in rel for tok in ("unknown", "conflict", "disagreement"))
        for row in state.derived.get(rel, set())
        if len(row) >= 2 and row[0] == REF and row[1] == "kp"
    ]
    assert conflict_outputs, (
        "conflicting vendor cycle statements for product 'kp' must produce an explicit unknown/conflict output row"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/platform-five-scenes.md: admission_assumption.dl must derive an explicit "
        "unknown outcome when step >= 32 rather than silently dropping eligible requests"
    ),
)
def test_admission_assumption_step_at_or_above_32_derives_explicit_unknown():
    model = compiler_pack.read(ROOT)
    program = compiler_rules.load(model.rules)

    total_requests = 35
    records: dict[str, list[dict]] = {
        "tenant_profile": [{"id": "standard", "zone": "tenant", "unlisted": "denied", "size": ["small"]}],
        "tenant_catalog_item": [{"id": "worker", "component": "worker"}],
        "tenant_catalog_offer": [{"id": "worker/small", "item": "worker", "size": "small"}],
        "offered_cores": [{"id": "worker/small", "cores": 1}],
        "pool_cores": [{"id": "pool-a", "cores": 100}],
        "tenant_service_request": [],
        "tenant_request_item": [],
    }
    for idx in range(1, total_requests + 1):
        req_id = f"team-a/svc-{idx:02d}"
        records["tenant_service_request"].append({
            "id": req_id,
            "tenant": "team-a",
            "service": f"svc-{idx:02d}",
            "profile": "standard",
            "submitted_at": f"2026-01-01T00:00:{idx:02d}Z",
        })
        records["tenant_request_item"].append({
            "id": f"{req_id}/worker",
            "tenant": "team-a",
            "service": f"svc-{idx:02d}",
            "item": "worker",
            "size": "small",
        })

    base_rows = compiler_facts.rows_of(model, records)
    output_rels = [name for name, rel in program.relations.items() if rel.role == "derived" and rel.explain is not None]
    unknown_outputs = tuple(sorted(
        rel for rel in output_rels
        if rel.startswith(("admission_", "request_")) and "unknown" in rel
    ))
    targets = ("request_ordinal", "admission_step", "request_outcome", "free_cores", *unknown_outputs)
    needed: set[str] = set()
    derived = set(program.derived())
    stack = list(targets)
    while stack:
        rel = stack.pop()
        if rel in needed or rel not in derived:
            continue
        needed.add(rel)
        stack.extend(dep for dep in program.deps(rel) if dep in derived and dep not in needed)

    with compiler_batch.connect(program, base_rows) as con:
        compiler_batch.compute(con, program, relations=needed)
        out = compiler_batch.read(con, program, targets)

    assert len(out["request_ordinal"]) == total_requests
    outcomes_by_req: dict[str, set[str]] = {}
    for req_id, status in out["request_outcome"]:
        outcomes_by_req.setdefault(req_id, set()).add(status)

    extra_unknown_reqs = {
        row[0]
        for rel in unknown_outputs
        for row in out[rel]
        if row
    }

    for idx in range(1, 33):
        req_id = f"team-a/svc-{idx:02d}"
        assert outcomes_by_req.get(req_id) == {"landed"}, (
            f"request {req_id} (step {idx - 1}) expected landed, got {outcomes_by_req.get(req_id)}"
        )

    for idx in range(33, total_requests + 1):
        req_id = f"team-a/svc-{idx:02d}"
        statuses = outcomes_by_req.get(req_id, set())
        explicit_unknown = ("unknown" in statuses) or (req_id in extra_unknown_reqs)
        assert explicit_unknown, (
            f"request {req_id} (step {idx - 1} >= 32) was silently dropped or misclassified: "
            f"request_outcome={statuses}, unknown_relations={sorted(extra_unknown_reqs)}"
        )
        assert not (statuses & {"landed", "capacity"}), (
            f"request {req_id} (step {idx - 1} >= 32) must not claim landed/capacity beside unknown: {statuses}"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/platform-five-scenes.md: admission_assumption.dl must reuse connection "
        "classification from tenant_connection_review.dl instead of duplicating isolated, "
        "unresolved, matrix, and unlisted profile classification rules"
    ),
)
def test_admission_assumption_reuses_tenant_connection_review():
    model = compiler_pack.read(ROOT)
    program = compiler_rules.load(model.rules)

    duplicated_low_level = {
        "tenant_connection_isolated",
        "tenant_connection_unresolved",
        "tenant_connection_matrix",
        "tenant_profile__unlisted",
    }
    admission_rules = [r for r in program.rules.values() if r.module == "admission_assumption"]
    assert admission_rules, "expected compiled rules from admission_assumption module"

    offending = [
        (r.id, lit.atom.relation)
        for r in admission_rules
        for lit in r.body
        if lit.atom.relation in duplicated_low_level
    ]
    assert offending == [], (
        f"admission_assumption.dl still duplicates low-level connection classification predicates: {offending}"
    )

    review_module_relations = {
        r.head.relation for r in program.rules.values() if r.module == "tenant_connection_review"
    }
    review_deps = _transitive_deps(program, "tenant_connection_review") | {"tenant_connection_review"}
    allowed_classification = (review_module_relations & review_deps) - duplicated_low_level

    for head in ("admission_request_denied", "admission_request_review"):
        direct_body_rels = {
            lit.atom.relation
            for r in admission_rules
            if r.head.relation == head
            for lit in r.body
        }
        assert direct_body_rels & allowed_classification, (
            f"{head} does not consume connection classification from tenant_connection_review.dl; "
            f"direct body relations={sorted(direct_body_rels)}"
        )
