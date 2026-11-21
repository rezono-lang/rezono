"""Norm standing follows the latest valid ruling, only when the authority intake covers the cutoff.

Expectation source: decisions/platform-norm-standing.md, section "Acceptance". The reference date is 1 March 2026.
Rulings are std-decision records; their effective start is the decision's valid_from_day. Authority coverage and
register coverage are separate receipts. The expected rows are written here by hand from the authored records.
"""

import pytest

from case_support import verified

STANDING = "norm_standing"
UNKNOWN = "norm_standing_unknown"
CONFLICT = "norm_ruling_conflict"
REGISTER = "norm_registration_finding"
ON = "march"
SCOPE = "s-db"


def decision(key, start, state="in_force", end=None):
    record = {"id": key, "title": key, "state": state, "decider": ["audit-office"],
              "valid_from": f"2026-{start // 100:02}-{start % 100:02}", "valid_from_day": 20260000 + start}
    if end is not None:
        record.update(valid_until=f"2026-{end // 100:02}-{end % 100:02}", valid_until_day=20260000 + end)
    return record


def records(*extra, coverage=(SCOPE, 20260301), registered=None, register_covered=True):
    """The pass-jan ruling plus the rulings in `extra`: (key, start as MMDD, outcome, state, end). Every ruling
    is registered unless `registered` names the registered decisions."""
    rulings = [("pass-jan", 101, "pass", "in_force", None), *extra]
    registered = [key for key, *_ in rulings] if registered is None else registered
    data = {
        "norm_scope": [{"id": SCOPE, "norm": "encryption-at-rest", "subject": "orders-db"}],
        "decision": [decision(key, start, state, end) for key, start, _, state, end in rulings],
        "ruling": [{"id": key, "decision": key, "scope": SCOPE, "outcome": outcome}
                   for key, _, outcome, _, _ in rulings],
        "reference_date": [{"id": ON, "title": ON, "date": "2026-03-01", "day": 20260301}],
        "norm_register": [{"id": "register-4"}],
        "authority_coverage": [],
        "registration": [{"id": f"entry-{key}", "register": "register-4", "scope": SCOPE, "decision": key}
                         for key in registered],
        "register_coverage": [],
    }
    if coverage and coverage[0] != SCOPE:
        data["norm_scope"].append({"id": coverage[0], "norm": "encryption-at-rest", "subject": "cache"})
    if coverage:
        data["authority_coverage"].append({"id": "intake", "scope": coverage[0], "cutoff_day": coverage[1]})
    if register_covered:
        data["register_coverage"].append({"id": "register-scope", "register": "register-4", "scope": SCOPE})
    return {kind: rows for kind, rows in data.items() if rows}


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state, tuple(state.derived.get(name) for name in (STANDING, UNKNOWN, CONFLICT, REGISTER))


def leaf(leaves, relation, key):
    return any(rel == relation and row[0] == key for rel, row in leaves)


FAIL_FEB = ("fail-feb", 201, "fail", "in_force", None)
FAIL_JAN = ("fail-jan", 101, "fail", "in_force", None)
INCOMPLETE = {(SCOPE, ON, "authority-coverage-incomplete")}


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/platform-norm-standing.md: Derive norm_standing(scope, on, outcome), norm_standing_unknown(scope, on, reason) with reasons "
    "authority-coverage-incomplete, no-valid-ruling and latest-date-conflict, norm_ruling_conflict(scope, on, "
    "ruling, other) in both directions, and norm_registration_finding(scope, on, ruling, register, finding) for "
    "each valid ruling, with findings missing, register-coverage-incomplete and proposal-only, in "
    "rules/norm_standing.dl, using std-decision in_force_on. Declare NormScope (norm, subject), Ruling (decision: "
    "Decision, scope: NormScope, outcome pass or fail), AuthorityCoverage (scope: NormScope, cutoff_day), "
    "NormRegister, Registration (register: NormRegister, scope: NormScope, decision: Decision) and "
    "RegisterCoverage (register: NormRegister, scope: NormScope) in "
    "schema/norm_standing.yaml; no fact rows. Read decisions/platform-norm-standing.md."))
def test_norm_standing():
    model, state, result = outcome(records())
    assert result == ({(SCOPE, ON, "pass")}, set(), set(), set())
    leaves = verified(STANDING, (SCOPE, ON, "pass"), state=(model, state))
    for relation, key in (("authority_coverage__cutoff_day", "intake"), ("ruling__outcome", "pass-jan"),
                          ("decision__decider", "pass-jan")):
        assert leaf(leaves, relation, key), relation

    # A later valid ruling decides; an equally recent one that disagrees is a conflict with both keys.
    assert outcome(records(FAIL_FEB))[2] == ({(SCOPE, ON, "fail")}, set(), set(), set())
    model, state, result = outcome(records(FAIL_JAN))
    assert result == (set(), {(SCOPE, ON, "latest-date-conflict")},
                      {(SCOPE, ON, "pass-jan", "fail-jan"), (SCOPE, ON, "fail-jan", "pass-jan")}, set())
    leaves = verified(CONFLICT, (SCOPE, ON, "pass-jan", "fail-jan"), state=(model, state))
    assert leaf(leaves, "ruling__outcome", "pass-jan") and leaf(leaves, "ruling__outcome", "fail-jan")

    # Agreeing ties, later proposals and ended rulings leave the January pass standing, in any input order.
    for extra in (("pass-jan-2", 101, "pass", "in_force", None), ("fail-proposed", 215, "fail", "proposed", None),
                  ("fail-ended", 201, "fail", "in_force", 210)):
        assert outcome(records(extra))[2] == ({(SCOPE, ON, "pass")}, set(), set(), set()), extra
    reversed_data = {kind: list(reversed(rows)) for kind, rows in records(FAIL_FEB).items()}
    assert outcome(reversed_data)[2] == ({(SCOPE, ON, "fail")}, set(), set(), set())

    # Without authority coverage through the cutoff of this scope, nothing is known, whatever the visible rulings.
    for coverage in (None, (SCOPE, 20260228), ("s-cache", 20260301)):
        for extra in ((), (FAIL_FEB,), (FAIL_JAN,)):
            standing, unknown, _, _ = outcome(records(*extra, coverage=coverage))[2]
            assert (standing, {row for row in unknown if row[0] == SCOPE}) == (set(), INCOMPLETE), (coverage, extra)

    # Complete coverage and no valid ruling at all.
    only_proposal = records()
    only_proposal["decision"][0]["state"] = "proposed"
    assert outcome(only_proposal)[2][:2] == (set(), {(SCOPE, ON, "no-valid-ruling")})

    # The register varies on its own: a covered absence, an uncovered register, and an entry for a proposal only.
    assert outcome(records(registered=()))[2] == (
        {(SCOPE, ON, "pass")}, set(), set(), {(SCOPE, ON, "pass-jan", "register-4", "missing")})
    assert outcome(records(registered=(), register_covered=False))[2][3] == {
        (SCOPE, ON, "pass-jan", "register-4", "register-coverage-incomplete")}
    proposal = ("fail-proposed", 215, "fail", "proposed", None)
    assert outcome(records(proposal, registered=("fail-proposed",)))[2] == (
        {(SCOPE, ON, "pass")}, set(), set(), {(SCOPE, ON, "pass-jan", "register-4", "proposal-only")})
    # A later valid ruling missing from the register is missing too.
    assert outcome(records(FAIL_FEB, registered=("pass-jan",)))[2][3] == {
        (SCOPE, ON, "fail-feb", "register-4", "missing")}
