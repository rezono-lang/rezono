"""Independent acceptance case from decisions/run-probe-profile-budgets.md."""

import pytest

from checked_questions import MissingReaderQuestion, checked, registered


QUESTION = "probe-profile-budgets"
PACK = "probe-profiles"
DAY = "2026-01-15"
PROFILE = "sample"
OBSERVER = "observer"
PHASES = ("provision", "install", "cleanup")
EXPECTED_BUDGETS = {
    (PROFILE, "assisted", "provision", "600"),
    (PROFILE, "assisted", "install", "900"),
    (PROFILE, "assisted", "cleanup", "300"),
    (PROFILE, "automatic", "provision", "600"),
    (PROFILE, "automatic", "install", "420"),
    (PROFILE, "automatic", "cleanup", "300"),
}


def recorded_design(*, automatic_term=True, covered=True, physical=True):
    records = {
        "probe_profile": [{"id": PROFILE}],
        "probe_cell": [{"id": "cell-one", "part_of": PROFILE}],
        "probe_cluster": [{"id": "control", "part_of": "cell-one"},
                          {"id": "workers", "part_of": "cell-one"}],
        "probe_member": [{"id": "one-control", "part_of": "control"},
                         {"id": "one-worker", "part_of": "workers"},
                         {"id": "other-worker", "part_of": "workers"}],
        "probe_phase": [{"id": "provision", "precedes": ["install"]},
                        {"id": "install", "precedes": ["cleanup"]}, {"id": "cleanup"}],
        "probe_storage_variant": [{"id": "assisted", "storage": "shared-store", "installation": "assisted"},
                                  {"id": "automatic", "storage": "shared-store", "installation": "automatic"}],
        "reference_date": [{"id": "planning-day", "title": DAY, "day": 20260115}],
        "probe_snapshot": [{"id": "planning-cut", "profile": PROFILE, "reference_date": "planning-day",
                            "membership_complete": "complete"}],
    }
    terms = {(variant, phase): seconds for variant, amounts in (("assisted", (600, 900, 300)),
                                                                ("automatic", (600, 420, 300)))
             for phase, seconds in zip(PHASES, amounts, strict=True)}
    if not automatic_term:
        del terms["automatic", "install"]
    approvals = [
        {"id": f"budget-{v}-{p}", "profile": PROFILE, "variant": v, "phase": p,
         "decision": f"decide-{v}-{p}", "seconds": seconds}
        for (v, p), seconds in terms.items()
    ]
    decisions = [
        {"id": row["decision"], "title": row["decision"],
         "decider": ["probe-authority"], "decided_on": DAY, "valid_from": DAY, "valid_from_day": 20260115,
         "state": "in_force"} for row in approvals
    ]
    physical_decision = {"id": "decide-physical", "title": "Physical", "decider": ["probe-authority"],
                         "decided_on": "2026-01-01", "valid_from": "2026-01-01", "valid_from_day": 20260101,
                         "state": "in_force"}
    if not physical:
        physical_decision.update(state="withdrawn", valid_until=DAY, valid_until_day=20260115)
    decisions.append(physical_decision)
    approved = {
        "decision": decisions,
        "probe_phase_budget": approvals,
        "probe_physical_requirement": [{"id": "physical-term", "profile": PROFILE, "cell": "cell-one",
                                        "decision": "decide-physical", "requirement": "required"}],
        "probe_term_coverage": [{"id": "decision-cut", "snapshot": "planning-cut"}] if covered else [],
    }
    access = {
        "role": [{"id": OBSERVER, "title": "Observer", "capability": ["read"]}],
        "probe_budget_read_grant": [{"id": f"show-{v}-{p}", "role": OBSERVER, "budget": f"budget-{v}-{p}"}
                                   for v, p in terms if (v, p) != ("automatic", "install")],
    }
    return {"profile-design.yaml": records, "profile-decisions.yaml": approved, "profile-grants.yaml": access}


@pytest.mark.xfail(strict=True, raises=MissingReaderQuestion, reason=(
    "Provide probe-profiles and publish probe-profile-budgets reader metadata and grounds. "
    "Compile membership counts, phase/variant budgets, effective physical decisions and complete-scope "
    "findings. Read decisions/run-probe-profile-budgets.md. Write in run/packs/probe-profiles/."
))
def test_probe_profile_budgets(tmp_path):
    registered(QUESTION, __file__, "test_probe_profile_budgets")
    checked(PACK, tmp_path / "plain").question(QUESTION)
    visible = checked(PACK, tmp_path / "complete", recorded_design(),
                      {"checker": "complete", OBSERVER: "may_read"})
    budgets = visible.question(QUESTION)
    assert visible.rows(budgets) == EXPECTED_BUDGETS
    assert visible.rows("probe_cluster_size") == {(PROFILE, "cell-one", "control", "1"),
                                                  (PROFILE, "cell-one", "workers", "2")}
    assert visible.rows("probe_profile_total") == {(PROFILE, "1", "2", "3")}
    requirement = (PROFILE, "cell-one", "required")
    assert {"cell-one", "physical-term", "decide-physical"} <= visible.ground_ids("probe_physical", requirement)
    install = (PROFILE, "automatic", "install", "420")
    assert {"budget-automatic-install", "decide-automatic-install"} <= visible.ground_ids(budgets, install)
    observer = visible.for_role(OBSERVER)
    assert (PROFILE, "assisted", "install", "900") in observer.rows(budgets)
    assert install not in observer.rows(budgets) and (budgets, install) not in observer.witnesses

    incomplete = checked(PACK, tmp_path / "missing-term", recorded_design(automatic_term=False))
    missing = (PROFILE, "automatic", "install", "missing_budget")
    assert incomplete.rows(budgets) == EXPECTED_BUDGETS - {install}
    assert {"planning-cut", "decision-cut"} <= incomplete.ground_ids("probe_budget_status", missing)
    unknown = checked(PACK, tmp_path / "unknown-term", recorded_design(automatic_term=False, covered=False))
    assert unknown.rows(budgets) == EXPECTED_BUDGETS - {install}
    assert unknown.rows("probe_budget_status") == {(PROFILE, "automatic", "install", "unknown")}
    withdrawn = checked(PACK, tmp_path / "withdrawn", recorded_design(physical=False))
    assert withdrawn.rows("probe_physical") == set()
    assert withdrawn.rows(budgets) == EXPECTED_BUDGETS
