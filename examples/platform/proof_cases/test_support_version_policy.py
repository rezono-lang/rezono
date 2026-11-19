"""Support severity of a pinned version follows the vendor's cycle dates and the policy in force, beside the register.

Expectation source: decisions/platform-support-version-policy.md. The fixture is synthetic and kept apart from the
real product evidence: day positions on one support axis, a dated policy decision and a dated assessment register.
A cycle whose support end lies at most `warning_days` after the reference position is a warning; a cycle that
still holds beyond that is ok; an ended cycle is critical. The expected rows are written here by hand.
"""

import copy

import pytest

from case_support import verified

LATEST = "latest_supported_cycle"
SEVERITY = "support_severity"
UNKNOWN = "support_severity_unknown"
DRIFT = "support_severity_drift"
REF = "spring-check"
NO = "no"


def decision(key, state="in_force", supersedes=None):
    record = {"id": key, "title": key, "state": state, "decider": ["platform-board"],
              "valid_from": "2026-01-01", "valid_from_day": 20260101}
    if supersedes:
        record["supersedes"] = [supersedes]
    return record


def cycle(key, series, start, end):
    return {"id": key, "on_axis": "support-days", "start": start, "end": end, "product": "kp", "series": series,
            "source_url": f"https://vendor.example.org/support/{series}",
            "source_sha256": format(start * 1000 + end, "064x")}


def records():
    service = lambda key: {"id": key, "product": "kp", "role": "app-role", "step": 1}
    return {
        "zone": [{"id": "inner", "outside": NO, "entry_boundary": NO, "isolated_recovery": NO, "workload": "yes"}],
        "cluster_class": [{"id": "shared"}],
        "platform_role": [{"id": "app-role", "zone": "inner", "cluster_class": "shared", "runs_images": "yes",
                           "build_authority": NO}],
        "product": [{"id": "kp"}],
        "service": [service("svc"), service("svc-new")],
        "release": [{"id": "kp-1.9.3", "product": "kp", "released_on_day": 1, "stable": "yes", "version": "1.9.3",
                     "series": "1.9"},
                    {"id": "kp-2.0.0", "product": "kp", "released_on_day": 2, "stable": "yes", "version": "2.0.0",
                     "series": "2.0"}],
        "pin": [{"id": "pin-svc", "service": "svc", "release": "kp-1.9.3"},
                {"id": "pin-svc-new", "service": "svc-new", "release": "kp-2.0.0"}],
        "axis": [{"id": "support-days"}],
        # Label order differs from start order: 1.10 starts after 1.9. 1.10 and 1.10-lts start on the same day.
        # 1.11 starts last but its support has already ended. No vendor statement covers 2.0.
        "vendor_cycle_support": [cycle("kp-1.8", "1.8", 50, 150), cycle("kp-1.9", "1.9", 100, 320),
                                 cycle("kp-1.10", "1.10", 200, 500), cycle("kp-1.10-lts", "1.10-lts", 200, 700),
                                 cycle("kp-1.11", "1.11", 250, 290)],
        "reference_point": [{"id": "day-300", "on_axis": "support-days", "position": 300, "horizon": 0}],
        "reference_date": [{"id": "march", "title": "march", "day": 20260301}],
        "support_reference": [{"id": REF, "point": "day-300", "standing_on": "march"}],
        "decision": [decision("policy-30")],
        "support_policy": [{"id": "sp-30", "decision": "policy-30", "product": "kp", "warning_days": 30}],
        "support_assessment_entry": [{"id": "reg-svc", "revision": "register-12", "service": "svc", "series": "1.9",
                                      "severity": "warning"}],
    }


def outcome(data):
    from management_probes import compiled

    model, state = compiled(data)
    return model, state, tuple(state.derived.get(name) for name in (LATEST, SEVERITY, UNKNOWN, DRIFT))


def leaf(leaves, relation, key):
    return any(rel == relation and row[0] == key for rel, row in leaves)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "extra: decisions/platform-support-version-policy.md: Derive latest_supported_cycle(reference, product, cycle), support_severity(reference, service, cycle, "
    "severity), support_severity_unknown(reference, service, reason) with reasons pin-unmapped, cycle-conflict "
    "and policy-missing, and support_severity_drift(reference, service, cycle, derived, registered, entry) in "
    "rules/support_version_policy.dl, using std-time for holds and ended and std-decision in_force_on for the "
    "policy. Declare VendorCycleSupport (is_a Interval; product: Product, series, source_url, source_sha256), "
    "SupportReference (point: ReferencePoint, standing_on: ReferenceDate), SupportPolicy (decision: Decision, "
    "product: Product, warning_days) and SupportAssessmentEntry (revision, service: Service, series, severity) in "
    "schema/support_version_policy.yaml; no fact rows. Read decisions/platform-support-version-policy.md."))
def test_support_version_policy():
    data = records()
    model, state, (latest, severity, unknown, drift) = outcome(data)
    assert latest == {(REF, "kp", "kp-1.10"), (REF, "kp", "kp-1.10-lts")}
    assert severity == {(REF, "svc", "kp-1.9", "warning")}
    assert unknown == {(REF, "svc-new", "pin-unmapped")}
    assert drift == set()
    leaves = verified(SEVERITY, (REF, "svc", "kp-1.9", "warning"), state=(model, state))
    for relation, key in (("pin__release", "pin-svc"), ("support_policy__warning_days", "sp-30"),
                          ("vendor_cycle_support__series", "kp-1.9"), ("support_reference__point", REF)):
        assert leaf(leaves, relation, key), relation

    # The threshold is inclusive: 20 days left is a warning at 20 and ok at 19.
    for days, expected in ((20, "warning"), (19, "ok")):
        changed = copy.deepcopy(data)
        changed["support_policy"][0]["warning_days"] = days
        assert outcome(changed)[2][1] == {(REF, "svc", "kp-1.9", expected)}

    # A proposed replacement changes nothing; the same replacement in force does.
    for state_of, expected in (("proposed", "warning"), ("in_force", "ok")):
        changed = copy.deepcopy(data)
        changed["decision"].append(decision("policy-10", state=state_of, supersedes="policy-30"))
        changed["decision"][1]["valid_from"], changed["decision"][1]["valid_from_day"] = "2026-02-01", 20260201
        changed["support_policy"].append({"id": "sp-10", "decision": "policy-10", "product": "kp", "warning_days": 10})
        assert outcome(changed)[2][1] == {(REF, "svc", "kp-1.9", expected)}

    # Without a policy, or with two vendor statements of one cycle that disagree, the severity is unknown.
    changed = copy.deepcopy(data)
    del changed["support_policy"]
    assert outcome(changed)[2][1:3] == (set(), {(REF, "svc-new", "pin-unmapped"), (REF, "svc", "policy-missing")})
    changed = copy.deepcopy(data)
    changed["vendor_cycle_support"].append(cycle("kp-1.9-reissued", "1.9", 100, 400))
    assert outcome(changed)[2][1:3] == (set(), {(REF, "svc-new", "pin-unmapped"), (REF, "svc", "cycle-conflict")})

    # A changed register severity changes the drift only.
    changed = copy.deepcopy(data)
    changed["support_assessment_entry"][0]["severity"] = "ok"
    model, state, (latest, severity, _, drift) = outcome(changed)
    row = (REF, "svc", "kp-1.9", "warning", "ok", "reg-svc")
    assert (severity, drift) == ({(REF, "svc", "kp-1.9", "warning")}, {row})
    leaves = verified(DRIFT, row, state=(model, state))
    assert leaf(leaves, "support_assessment_entry__severity", "reg-svc") and leaf(leaves, "pin__release", "pin-svc")
