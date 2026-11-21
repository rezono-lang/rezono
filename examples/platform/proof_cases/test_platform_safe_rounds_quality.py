"""Quality and soundness invariants for examples/platform/rules/platform_safe_rounds.dl.

Enforces decisions/safe-step-rounds.md §4 and decisions/standard-packs-everywhere.md §2:
- No vacuous `count >= 0` guards in platform_safe_blocker.
- No hardcoded fixture target/step/token names in platform_startup_goal.
- Offline restore interval verification requires stop/fence evidence beyond two boundary probes.
- platform_restore_goal checks backup copy age and suitability against policy.
- No hardcoded 'management/availability', 'unreachable', or 'empty' literals; read expectations
  from std-loop's LoopExpectation.
"""

from __future__ import annotations

from hashlib import sha256

import pytest

from case_support import ROOT
from rezono_compiler import batch as compiler_batch, pack as compiler_pack, rules as compiler_rules


def _load_platform():
    model = compiler_pack.read(ROOT)
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


def _is_var(term: str) -> bool:
    return term.startswith("?") or term == "_"


def _int_literal(term: str) -> int | None:
    try:
        return int(term)
    except ValueError:
        return None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_safe_rounds.dl must not use vacuous "
        "absent_needs >= 0 count guards just to pull a receipt into a witness "
        "(decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_safe_blocker_has_no_vacuous_count_guard():
    _, program = _load_platform()
    safe_round_rules = [r for r in program.rules.values() if r.module == "platform_safe_rounds"]
    assert safe_round_rules, "expected compiled rules from platform_safe_rounds module"

    vacuous: list[tuple[str, str, str, str]] = []
    for rule in safe_round_rules:
        count_vars = {agg.var for agg in rule.aggregates if agg.function == "count"}
        for cond in rule.conditions:
            left_int, right_int = _int_literal(cond.left), _int_literal(cond.right)
            if cond.left in count_vars and right_int is not None:
                if (cond.op == "ge" and right_int <= 0) or (cond.op == "gt" and right_int < 0):
                    vacuous.append((rule.id, cond.left, cond.op, cond.right))
            if cond.right in count_vars and left_int is not None:
                if (cond.op == "le" and left_int <= 0) or (cond.op == "lt" and left_int < 0):
                    vacuous.append((rule.id, cond.left, cond.op, cond.right))

    assert vacuous == [], (
        f"platform_safe_rounds.dl contains vacuous non-negativity count guards: {vacuous}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_safe_rounds.dl must derive "
        "platform_startup_goal target and required steps/tokens from an explicit declared target "
        "inventory rather than hardcoding fixture names (decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_startup_goal_derives_target_from_declared_inventory():
    _, program = _load_platform()
    startup_rules = [r for r in program.rules.values() if r.head.relation == "platform_startup_goal"]
    assert startup_rules, "expected compiled rules for platform_startup_goal"

    for rule in startup_rules:
        assert len(rule.head.terms) >= 3
        target_term = rule.head.terms[2]
        assert _is_var(target_term), (
            f"platform_startup_goal ({rule.id}) hardcodes constant target {target_term!r} "
            "instead of binding target from a declared inventory"
        )

    fixture_names = {
        "platform",
        "protect-entry",
        "expose-entry",
        "lb/listener",
        "lb/network-policy",
        "lb/router-policy",
        "restore-bad/network-probe",
    }
    related_rels = _transitive_deps(program, "platform_startup_goal") | {"platform_startup_goal"}
    local_rules = [
        r for r in program.rules.values()
        if r.module == "platform_safe_rounds" and r.head.relation in related_rels
    ]
    hardcoded: list[tuple[str, str]] = []
    for rule in local_rules:
        for term in rule.head.terms:
            if not _is_var(term) and term in fixture_names:
                hardcoded.append((rule.id, term))
        for lit in rule.body:
            for term in lit.atom.terms:
                if not _is_var(term) and term in fixture_names:
                    hardcoded.append((rule.id, term))

    assert hardcoded == [], (
        f"platform_startup_goal rules hardcode fixture step/token/target names: {hardcoded}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_safe_rounds.dl must satisfy "
        "decisions/safe-step-rounds.md §4 for proving management remained down using stop or fence "
        "evidence covering the interval, not just two boundary probes"
    ),
)
def test_platform_restore_interval_requires_stop_or_fence_evidence_beyond_boundary_probes():
    model, program = _load_platform()

    # Behavioral check: supplying ONLY two boundary probes plus a bare RestoreOfflineInterval
    # (with no stop/fence evidence) must NOT derive platform_restore_interval_verified.
    run = "rec-run"
    trial = "management-trial"
    digest = sha256(b"authored management dataset\n").hexdigest()
    inputs: dict[str, list[tuple[str, ...]]] = {
        "loop_active_run": [(run,)],
        "loop_expectation": [("management/availability",)],
        "loop_expectation__value": [("management/availability", "unreachable")],
        "loop_observation": [("start-obs",), ("readback-obs",), ("end-obs",)],
        "loop_observation__run": [("start-obs", run), ("readback-obs", run), ("end-obs", run)],
        "loop_observation__token": [
            ("start-obs", "management/availability"),
            ("readback-obs", "management-copy/payload"),
            ("end-obs", "management/availability"),
        ],
        "loop_observation__state": [("start-obs", "known"), ("readback-obs", "known"), ("end-obs", "known")],
        "loop_observation__value": [
            ("start-obs", "unreachable"),
            ("readback-obs", digest),
            ("end-obs", "unreachable"),
        ],
        "loop_observation__event_time": [("start-obs", "9"), ("readback-obs", "15"), ("end-obs", "19")],
        "loop_observation__reason": [("start-obs", "start-obs"), ("readback-obs", "readback-obs"), ("end-obs", "end-obs")],
        "restore_offline_interval": [("fence-1",)],
        "restore_offline_interval__run": [("fence-1", run)],
        "restore_offline_interval__trial": [("fence-1", trial)],
        "restore_offline_interval__start_evidence": [("fence-1", "start-obs")],
        "restore_offline_interval__end_evidence": [("fence-1", "end-obs")],
        "restore_offline_interval__readback_evidence": [("fence-1", "readback-obs")],
    }
    targets = ("platform_restore_interval_verified",)
    with compiler_batch.connect(program, inputs) as con:
        compiler_batch.compute(con, program, relations=_closure(program, targets))
        out = compiler_batch.read(con, program, targets)

    assert out["platform_restore_interval_verified"] == set(), (
        "two boundary probes without independent stop/fence coverage evidence must not verify "
        f"platform_restore_interval_verified; got {out['platform_restore_interval_verified']}"
    )

    # Schema check: RestoreOfflineInterval must carry stop/fence evidence beyond boundary probes.
    interval_kind = model.kinds.get("restore_offline_interval")
    boundary_only_slots = {"id", "run", "trial", "start_evidence", "end_evidence", "readback_evidence"}
    if interval_kind is not None:
        extra_slots = set(interval_kind.slots) - boundary_only_slots
        assert extra_slots, (
            "RestoreOfflineInterval only carries boundary probe references "
            f"{sorted(interval_kind.slots)}; it must bind stop or fence evidence covering the interval"
        )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_restore_goal must verify backup copy "
        "age and suitability against the governing backup policy before completing "
        "(decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_restore_goal_checks_backup_copy_age_and_suitability():
    _, program = _load_platform()

    run = "rec-run"
    cut = "restored-cut"
    trial = "management-trial"
    backup = "stale-copy"
    capture = "capture-1"
    readback = "readback-1"
    dataset = "management-catalog"
    digest = sha256(b"stale management dataset\n").hexdigest()

    base_inputs: dict[str, list[tuple[str, ...]]] = {
        "loop_active_run": [(run,)],
        "loop_sweep_receipt": [(cut,)],
        "loop_sweep_receipt__run": [(cut, run)],
        "loop_sweep_receipt__event_time": [(cut, "20")],
        "loop_completion": [("comp-restore",)],
        "loop_completion__run": [("comp-restore", run)],
        "loop_completion__step": [("comp-restore", "restore-copy")],
        "loop_completion__token": [("comp-restore", "management-copy/payload")],
        "loop_completion__reason": [("comp-restore", "observed-restored")],
        "loop_expectation": [("management/availability",), ("management-copy/payload",)],
        "loop_expectation__value": [
            ("management/availability", "unreachable"),
            ("management-copy/payload", digest),
        ],
        "loop_observation": [("start-obs",), (readback,), ("end-obs",)],
        "loop_observation__run": [("start-obs", run), (readback, run), ("end-obs", run)],
        "loop_observation__token": [
            ("start-obs", "management/availability"),
            (readback, "management-copy/payload"),
            ("end-obs", "management/availability"),
        ],
        "loop_observation__state": [("start-obs", "known"), (readback, "known"), ("end-obs", "known")],
        "loop_observation__value": [
            ("start-obs", "unreachable"),
            (readback, digest),
            ("end-obs", "unreachable"),
        ],
        "loop_observation__event_time": [("start-obs", "9"), (readback, "15"), ("end-obs", "19")],
        "loop_observation__reason": [("start-obs", "start-obs"), (readback, readback), ("end-obs", "end-obs")],
        "backup_trial": [(trial,)],
        "backup_trial__run": [(trial, run)],
        "backup_trial__backup": [(trial, backup)],
        "backup_trial__cluster": [(trial, "recovery")],
        "backup_capture": [(capture,)],
        "backup_capture__backup": [(capture, backup)],
        "backup_capture__run": [(capture, run)],
        "backup_capture__source_cluster": [(capture, "management")],
        "backup_capture__payload_sha256": [(capture, digest)],
        "backup_readback": [(readback,)],
        "backup_readback__trial": [(readback, trial)],
        "backup_readback__backup": [(readback, backup)],
        "backup_readback__run": [(readback, run)],
        "backup_readback__cluster": [(readback, "recovery")],
        "backup_readback__source_evidence": [(readback, capture)],
        "backup_readback__payload_sha256": [(readback, digest)],
        "restore_dataset_binding": [("bind-1",)],
        "restore_dataset_binding__trial": [("bind-1", trial)],
        "restore_dataset_binding__dataset": [("bind-1", dataset)],
        "restore_dataset_binding__backup": [("bind-1", backup)],
        "restore_dataset_binding__capture": [("bind-1", capture)],
        "restore_dependency_binding": [("dep-ctrl",), ("dep-cred",), ("dep-stor",)],
        "restore_dependency_binding__trial": [
            ("dep-ctrl", trial),
            ("dep-cred", trial),
            ("dep-stor", trial),
        ],
        "restore_dependency_binding__function": [
            ("dep-ctrl", "control"),
            ("dep-cred", "credentials"),
            ("dep-stor", "storage"),
        ],
        "restore_dependency_binding__provider": [
            ("dep-ctrl", "recovery-cp"),
            ("dep-cred", "recovery-vault"),
            ("dep-stor", "recovery-store"),
        ],
        "restore_dependency_binding__cluster": [
            ("dep-ctrl", "recovery"),
            ("dep-cred", "recovery"),
            ("dep-stor", "recovery"),
        ],
        "restore_offline_interval": [("fence-1",)],
        "restore_offline_interval__run": [("fence-1", run)],
        "restore_offline_interval__trial": [("fence-1", trial)],
        "restore_offline_interval__start_evidence": [("fence-1", "start-obs")],
        "restore_offline_interval__end_evidence": [("fence-1", "end-obs")],
        "restore_offline_interval__readback_evidence": [("fence-1", readback)],
    }

    # Case 1: backup copy is too old under the backup plan (9 days old vs max_age_days=2).
    too_old_inputs = {
        **base_inputs,
        "backup_plan": [("mgmt-plan",)],
        "backup_plan__service": [("mgmt-plan", "management")],
        "backup_plan__dataset": [("mgmt-plan", dataset)],
        "backup_plan__target": [("mgmt-plan", "vault")],
        "backup_plan__decided_by": [("mgmt-plan", "daily-backup-policy")],
        "backup_decision": [("daily-backup-policy",)],
        "backup_decision__as_of": [("daily-backup-policy", "2026-06-10")],
        "backup_decision__max_age_days": [("daily-backup-policy", "2")],
        "backup_inventory": [("scan-mgmt",)],
        "backup_inventory__service": [("scan-mgmt", "management")],
        "backup_inventory__target": [("scan-mgmt", "vault")],
        "backup_inventory__day": [("scan-mgmt", "2026-06-10")],
        "backup_inventory__complete": [("scan-mgmt", "true")],
        "backup_copy": [(backup,)],
        "backup_copy__service": [(backup, "management")],
        "backup_copy__target": [(backup, "vault")],
        "backup_copy__taken": [(backup, "2026-06-01")],
    }
    targets = ("platform_restore_goal", "managed_backup_state")
    with compiler_batch.connect(program, too_old_inputs) as con:
        compiler_batch.compute(con, program, relations=_closure(program, targets))
        out_old = compiler_batch.read(con, program, targets)

    assert out_old["platform_restore_goal"] == set(), (
        "platform_restore_goal must reject a backup copy that is too old / ineligible under "
        f"backup policy; managed_backup_state={out_old['managed_backup_state']}, "
        f"platform_restore_goal={out_old['platform_restore_goal']}"
    )

    # Case 2: without any backup freshness/suitability evidence at all, goal must not complete.
    with compiler_batch.connect(program, base_inputs) as con:
        compiler_batch.compute(con, program, relations=_closure(program, ("platform_restore_goal",)))
        out_missing = compiler_batch.read(con, program, ("platform_restore_goal",))

    assert out_missing["platform_restore_goal"] == set(), (
        "platform_restore_goal must not complete without verified backup copy age and suitability; "
        f"got {out_missing['platform_restore_goal']}"
    )

    deps = _transitive_deps(program, "platform_restore_goal")
    assert any(tok in dep for dep in deps for tok in ("backup_state", "backup_plan", "backup_copy", "eligible")), (
        f"platform_restore_goal does not depend on any backup age/suitability relation: {sorted(deps)}"
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_safe_rounds.dl must not hardcode "
        "literal 'management/availability', 'unreachable', or 'empty' in rules; read expectations "
        "from std-loop's LoopExpectation (decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_safe_rounds_reads_expectations_from_loop_expectation_without_hardcoded_literals():
    _, program = _load_platform()
    safe_round_rules = [r for r in program.rules.values() if r.module == "platform_safe_rounds"]
    assert safe_round_rules, "expected compiled rules from platform_safe_rounds module"

    forbidden_literals = {"management/availability", "unreachable", "empty"}
    found: list[tuple[str, str]] = []
    for rule in safe_round_rules:
        terms: list[str] = list(rule.head.terms)
        for lit in rule.body:
            terms.extend(lit.atom.terms)
        for agg in rule.aggregates:
            terms.extend(agg.atom.terms)
        for cond in rule.conditions:
            terms.extend((cond.left, cond.right))
        for term in terms:
            if not _is_var(term) and term in forbidden_literals:
                found.append((rule.id, term))

    assert found == [], (
        f"platform_safe_rounds.dl hardcodes forbidden expectation/scope literals: {found}"
    )

    offline_deps = _transitive_deps(program, "platform_restore_interval_verified")
    expectation_rels = {"loop_expectation", "loop_expectation__value", "expectation", "desired"}
    assert offline_deps & expectation_rels, (
        "platform_restore_interval_verified must read expected offline token/value from "
        f"LoopExpectation; deps={sorted(offline_deps)}"
    )
