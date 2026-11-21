"""Quality invariants for examples/platform/rules/platform_safe_rounds.dl.

Enforces decisions/safe-step-rounds.md §4 and decisions/standard-packs-everywhere.md §2:
- No vacuous `count >= 0` guards in platform_safe_blocker.
- No hardcoded fixture target/step/token names in platform_startup_goal (or any helper reaching it).
- No hardcoded 'management/availability', 'unreachable', or 'empty' literals; read expectations
  from std-loop's LoopExpectation.
"""

from __future__ import annotations

import pytest

from case_support import ROOT
from rezono_compiler import pack as compiler_pack, rules as compiler_rules


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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
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


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
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
