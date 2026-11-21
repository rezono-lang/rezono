"""Explicit invalid multiplicity outcomes and single-source connection classification in platform rules.

Covers two defects in examples/platform/rules/:
- Under rezono 1 (decisions/language-rezono-1.md §7), ambiguous_provider retires and functional
  needs(a, f) must emit exact ('invalid', 'multiple_values', '') with all candidate providers as witness.
- admission_assumption.dl duplicates connection classification from tenant_connection_review.dl.
"""

from __future__ import annotations

import copy

import pytest

from case_support import ROOT, verified
from rezono_compiler import pack as compiler_pack, rules as compiler_rules

NO = "no"


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
    raises=AssertionError,
    reason=(
        "M3: decisions/language-rezono-1.md: section 7. Once examples/platform/rules/ converts to "
        "rezono 1, ambiguous_provider retires and functional needs(a, f) must emit exact "
        "('invalid', 'multiple_values', '') with every competing candidate provider as witness when "
        "a consumer has multiple unchosen providers. "
        "Waits for compiler/tests/rezono/test_lower_rezono_1_derived.py--test_lower_rezono_1_derived, "
        "checker/tests/test_functional_exact_reasons.py--test_checker_enforces_exact_functional_empty_and_conflict_reasons, "
        "and the rezono 1 conversion of examples/platform/rules/."
    ),
)
def test_ambiguous_provider_produces_invalid_multiple_values_in_needs():
    from management_probes import compiled

    data = _ambiguous_provider_records()
    model, state = compiled(data)

    assert "ambiguous_provider" not in set(state.derived), (
        "ambiguous_provider must be retired on rezono 1 conversion (decisions/language-rezono-1.md §7)"
    )

    invalid_row = ("shop", "login", "invalid", "multiple_values", "")
    needs_rows = state.derived.get("needs", set())
    assert invalid_row in needs_rows, (
        "consumer 'shop' has multiple unchosen providers ('idp-a', 'idp-b') for 'login', yet functional "
        f"needs did not emit {invalid_row!r}; got {sorted(r for r in needs_rows if r[:2] == ('shop', 'login'))}"
    )

    leaves = verified("needs", invalid_row, state=(model, state))
    assert any(r == "demand__function" and k[0] == "d-login" for r, k in leaves), (
        f"witness for {invalid_row!r} must cite demand d-login; leaves={sorted(leaves)}"
    )
    assert any(k and k[0] == "idp-a" for _, k in leaves) and any(k and k[0] == "idp-b" for _, k in leaves), (
        f"witness for {invalid_row!r} must cite both competing candidate providers idp-a and idp-b; "
        f"leaves={sorted(leaves)}"
    )

    # Control: once an explicit Choice selects idp-a, invalid multiple_values disappears and needs is known.
    resolved = copy.deepcopy(data)
    resolved["choice"] = [{"id": "c-shop-login", "service": "shop", "function": "login", "provider": "idp-a"}]
    _, resolved_state = compiled(resolved)
    resolved_needs = resolved_state.derived.get("needs", set())
    assert invalid_row not in resolved_needs
    assert ("shop", "login", "known", "", "idp-a") in resolved_needs


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
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
