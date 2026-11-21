"""Quality invariants for examples/platform/rules/platform_safe_rounds.dl.

Enforces decisions/safe-step-rounds.md §4 and decisions/standard-packs-everywhere.md §2:
- No vacuous `count >= 0` guards in platform_safe_blocker (or any helper reaching it), while its
  verified witness still cites the admitted absence receipt leaves.
- No hardcoded fixture target/step/token names in platform_startup_goal (or any helper reaching it).
- No hardcoded 'management/availability', 'unreachable', or 'empty' literals in any rule reaching
  the safe-rounds goals; read expectations from std-loop's LoopExpectation so a different
  LoopExpectation changes the verified restore-interval outcome.
"""

from __future__ import annotations

from functools import cache
from hashlib import sha256

import pytest

from case_support import ROOT, verified
from rezono_compiler import batch as compiler_batch, facts as compiler_facts
from rezono_compiler import pack as compiler_pack, rules as compiler_rules
from rules_support import State

SAFE_ROUND_GOALS = (
    "platform_safe_frontier",
    "platform_safe_blocker",
    "platform_startup_goal",
    "platform_restore_goal",
)


@cache
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


def _is_var(term: str) -> bool:
    return term.startswith("?") or term == "_"


def _int_literal(term: str) -> int | None:
    try:
        return int(term)
    except ValueError:
        return None


def _safe_blocker_absence_rows(model):
    run = "startup-receipt-run"
    cut = "empty"
    scope = {"run": run, "collector": "router", "window": cut}
    records = {
        "loop_active_run": [{"id": run}],
        "loop_sweep_receipt": [{"id": cut, "run": run, "event_time": 10}],
        "loop_step": [{"id": "expose-entry"}],
        "loop_requirement": [
            {
                "id": "expose-needs-router",
                "run": run,
                "step": "expose-entry",
                "token": "lb/router-policy",
                "reason": "effective-protection",
            },
        ],
        "flow_sweep_window": [{**scope, "id": "empty-router", "start": 0, "stop": 10}],
        "flow_expected_node": [{**scope, "id": "empty-router-lb", "node": "lb"}],
        "flow_node_report": [
            {**scope, "id": "empty-router-report", "node": "lb", "first": 0, "last": 10, "gaps": 0, "lost": 0},
        ],
        "loop_observation": [
            {
                "id": "empty-router-absent",
                "run": run,
                "token": "lb/router-policy",
                "event_time": 9,
                "state": "absent",
                "value": "missing",
                "reason": "empty-router-absent",
                "scope": "router",
                "sweep": cut,
            },
        ],
        "loop_step_safety_check": [
            {
                "id": "expose-unprotected-at-empty",
                "run": run,
                "step": "expose-entry",
                "cut": cut,
                "obligation": "unprotected-listener",
                "verdict": "refuted",
                "reason": "violated-invariant",
            },
        ],
    }
    rows = compiler_facts.rows_of(model, records)
    rows["verified_receipt"] = [
        ("receipt-router", "router-observer", "scope-router", "cut-10", "inv-router", "cnt-router"),
    ]
    rows["verified_member"] = [
        ("receipt-router", "member-lb", 0, "sweep-node"),
        ("receipt-router", "member-lb", 1, run),
        ("receipt-router", "member-lb", 2, "router"),
        ("receipt-router", "member-lb", 3, cut),
        ("receipt-router", "member-lb", 4, "lb"),
    ]
    return run, cut, rows


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: platform_safe_rounds.dl (and any rule reaching "
        "platform_safe_blocker) must not use vacuous absent_needs >= 0 count guards, while the "
        "verified witness of platform_safe_blocker must still cite the admitted absence receipt "
        "leaves (decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_safe_blocker_has_no_vacuous_count_guard():
    model, program = _load_platform()
    blocker_rels = _transitive_deps(program, "platform_safe_blocker") | {"platform_safe_blocker"}
    checked_rules = [
        r for r in program.rules.values()
        if r.module == "platform_safe_rounds" or r.head.relation in blocker_rels
    ]
    assert checked_rules, "expected compiled rules reaching platform_safe_blocker"

    # Execution witness check: deleting the aggregate without genuinely linking the absence receipt
    # must fail because the verified blocker proof leaves must cite the admitted absence receipt.
    run, cut, rows = _safe_blocker_absence_rows(model)
    state = State(model, program, "safe-blocker-absence-receipt", rows)
    blocker_key = (run, cut, "expose-entry", "unprotected-listener")
    leaves = verified("platform_safe_blocker", blocker_key, state=(model, state))
    assert ("flow_node_report__node", ("empty-router-report", "lb")) in leaves, (
        "verified witness of platform_safe_blocker must cite the admitted absence sweep report "
        f"('flow_node_report__node', ('empty-router-report', 'lb')); leaves={sorted(leaves)}"
    )
    assert any(rel == "verified_receipt" and key[0] == "receipt-router" for rel, key in leaves), (
        "verified witness of platform_safe_blocker must cite the admitted completeness receipt "
        f"'receipt-router'; leaves={sorted(leaves)}"
    )

    # Structural check: no vacuous count >= 0 (or equivalent) guard anywhere reaching the blocker.
    vacuous: list[tuple[str, str, str, str, str]] = []
    for rule in checked_rules:
        count_vars = {agg.var for agg in rule.aggregates if agg.function == "count"}
        for cond in rule.conditions:
            left_int, right_int = _int_literal(cond.left), _int_literal(cond.right)
            if cond.left in count_vars and right_int is not None:
                if (cond.op == "ge" and right_int <= 0) or (cond.op == "gt" and right_int < 0):
                    vacuous.append((rule.module, rule.id, cond.left, cond.op, cond.right))
            if cond.right in count_vars and left_int is not None:
                if (cond.op == "le" and left_int <= 0) or (cond.op == "lt" and left_int < 0):
                    vacuous.append((rule.module, rule.id, cond.left, cond.op, cond.right))

    assert vacuous == [], (
        f"rules reaching platform_safe_blocker contain vacuous non-negativity count guards: {vacuous}"
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
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
    reaching_rules = [
        r for r in program.rules.values()
        if r.head.relation in related_rels
    ]
    hardcoded: list[tuple[str, str, str]] = []
    for rule in reaching_rules:
        terms: list[str] = list(rule.head.terms)
        for lit in rule.body:
            terms.extend(lit.atom.terms)
        for agg in rule.aggregates:
            terms.extend(agg.atom.terms)
        for cond in rule.conditions:
            terms.extend((cond.left, cond.right))
        for term in terms:
            if not _is_var(term) and term in fixture_names:
                hardcoded.append((rule.module, rule.id, term))

    assert hardcoded == [], (
        f"rules reaching platform_startup_goal hardcode fixture step/token/target names: {hardcoded}"
    )


def _eval_restore_interval(
    program,
    *,
    token: str,
    expected_value: str,
    observed_value: str,
    mid_value: str | None = None,
) -> tuple[set[tuple[str, ...]], set[tuple[str, ...]], tuple[str, str, str, str]]:
    run = "rec-expectation-run"
    trial = "management-trial"
    digest = sha256(b"authored management dataset\n").hexdigest()
    targets = ("platform_restore_interval_broken", "platform_restore_interval_verified")
    needed = set(targets)
    for target in targets:
        needed |= _transitive_deps(program, target)
    needed &= set(program.derived())

    obs_ids = [("start-obs",), ("readback-obs",), ("end-obs",)]
    obs_run = [("start-obs", run), ("readback-obs", run), ("end-obs", run)]
    obs_token = [("start-obs", token), ("readback-obs", "management-copy/payload"), ("end-obs", token)]
    obs_state = [("start-obs", "known"), ("readback-obs", "known"), ("end-obs", "known")]
    obs_value = [("start-obs", observed_value), ("readback-obs", digest), ("end-obs", observed_value)]
    obs_time = [("start-obs", "9"), ("readback-obs", "15"), ("end-obs", "19")]
    obs_reason = [("start-obs", "start-obs"), ("readback-obs", "readback-obs"), ("end-obs", "end-obs")]

    if mid_value is not None:
        obs_ids.append(("mid-obs",))
        obs_run.append(("mid-obs", run))
        obs_token.append(("mid-obs", token))
        obs_state.append(("mid-obs", "known"))
        obs_value.append(("mid-obs", mid_value))
        obs_time.append(("mid-obs", "14"))
        obs_reason.append(("mid-obs", "mid-obs"))

    inputs: dict[str, list[tuple[str, ...]]] = {
        "loop_active_run": [(run,)],
        "loop_expectation": [(token,)],
        "loop_expectation__value": [(token, expected_value)],
        "loop_observation": obs_ids,
        "loop_observation__run": obs_run,
        "loop_observation__token": obs_token,
        "loop_observation__state": obs_state,
        "loop_observation__value": obs_value,
        "loop_observation__event_time": obs_time,
        "loop_observation__reason": obs_reason,
        "restore_offline_interval": [("fence-1",)],
        "restore_offline_interval__run": [("fence-1", run)],
        "restore_offline_interval__trial": [("fence-1", trial)],
        "restore_offline_interval__start_evidence": [("fence-1", "start-obs")],
        "restore_offline_interval__end_evidence": [("fence-1", "end-obs")],
        "restore_offline_interval__readback_evidence": [("fence-1", "readback-obs")],
    }
    with compiler_batch.connect(program, inputs) as con:
        compiler_batch.compute(con, program, relations=needed)
        out = compiler_batch.read(con, program, targets)
    return (
        out["platform_restore_interval_broken"],
        out["platform_restore_interval_verified"],
        (run, trial, "readback-obs", digest),
    )


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M2: decisions/standard-packs-everywhere.md: no rule reaching the safe-rounds goals may "
        "hardcode literal 'management/availability', 'unreachable', or 'empty'; read expectations "
        "from std-loop's LoopExpectation so changing LoopExpectation changes the outcome "
        "(decisions/safe-step-rounds.md §4)"
    ),
)
def test_platform_safe_rounds_reads_expectations_from_loop_expectation_without_hardcoded_literals():
    _, program = _load_platform()
    reaching_rels = set(SAFE_ROUND_GOALS)
    for goal in SAFE_ROUND_GOALS:
        reaching_rels |= _transitive_deps(program, goal)
    checked_rules = [
        r for r in program.rules.values()
        if r.module == "platform_safe_rounds" or r.head.relation in reaching_rels
    ]
    assert checked_rules, "expected compiled rules reaching the safe-rounds goals"

    forbidden_literals = {"management/availability", "unreachable", "empty"}
    found: list[tuple[str, str, str]] = []
    for rule in checked_rules:
        terms: list[str] = list(rule.head.terms)
        for lit in rule.body:
            terms.extend(lit.atom.terms)
        for agg in rule.aggregates:
            terms.extend(agg.atom.terms)
        for cond in rule.conditions:
            terms.extend((cond.left, cond.right))
        for term in terms:
            if not _is_var(term) and term in forbidden_literals:
                found.append((rule.module, rule.id, term))

    assert found == [], (
        f"rules reaching safe-rounds goals hardcode forbidden expectation/scope literals: {found}"
    )

    offline_deps = _transitive_deps(program, "platform_restore_interval_verified")
    expectation_rels = {"loop_expectation", "loop_expectation__value", "expectation", "desired"}
    assert offline_deps & expectation_rels, (
        "platform_restore_interval_verified must read expected offline token/value from "
        f"LoopExpectation; deps={sorted(offline_deps)}"
    )

    # Execution case: a different LoopExpectation token and value must drive the outcome.
    broken, verified_rows, expected_row = _eval_restore_interval(
        program,
        token="control-plane/fenced",
        expected_value="fenced",
        observed_value="fenced",
    )
    assert broken == set() and verified_rows == {expected_row}, (
        "alternative LoopExpectation ('control-plane/fenced' -> 'fenced') must verify the restore "
        f"interval; got broken={broken}, verified={verified_rows}"
    )

    # Changing ONLY LoopExpectation to another expected value must flip the outcome to unverified.
    _, mismatched_verified, _ = _eval_restore_interval(
        program,
        token="control-plane/fenced",
        expected_value="isolated",
        observed_value="fenced",
    )
    assert mismatched_verified == set(), (
        "changing LoopExpectation from 'fenced' to 'isolated' without changing observations must "
        f"not verify the interval; got {mismatched_verified}"
    )

    # Matching the updated LoopExpectation verifies the interval again.
    broken_alt, verified_alt, _ = _eval_restore_interval(
        program,
        token="control-plane/fenced",
        expected_value="isolated",
        observed_value="isolated",
    )
    assert broken_alt == set() and verified_alt == {expected_row}, (
        "observations matching updated LoopExpectation ('isolated') must verify the interval; "
        f"got broken={broken_alt}, verified={verified_alt}"
    )

    # A mid-interval observation differing from the LoopExpectation must break the interval.
    broken_mid, verified_mid, _ = _eval_restore_interval(
        program,
        token="control-plane/fenced",
        expected_value="fenced",
        observed_value="fenced",
        mid_value="reachable",
    )
    assert broken_mid == {("fence-1",)} and verified_mid == set(), (
        "mid-interval observation differing from LoopExpectation must break the interval; "
        f"got broken={broken_mid}, verified={verified_mid}"
    )
