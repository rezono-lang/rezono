"""Whole-order costs and preference authority, from decisions/run-physical-nested-allocation.md."""

import pytest

from checked_questions import MissingReaderQuestion, checked, registered


QUESTION = "physical-or-nested"
PACK = "offer-selection"
WORKLOAD, SCOPE, AUTHORITY = "workload-one", "order-one", "run-authority"
DAY = "2026-01-15"
PHYSICAL = ("physical",)
NESTED = ("nested",)


def decision(name, supersedes=None):
    record = {"id": name, "title": name, "decider": [AUTHORITY], "decided_on": DAY,
              "valid_from": DAY, "valid_from_day": 20260115, "state": "in_force"}
    if supersedes is not None:
        record["supersedes"] = [supersedes]
    return record


def recorded_allocation(preferences=(), *, coverage=SCOPE, third=False, setup=False, account_limit=4,
                        missing_disk=False, complete_candidates=True, supersedes=False):
    members = ["member-one", "member-two", "member-three"]
    placements = [("physical", ("p1", "p2", "p3")), ("nested", ("n1", "n1", "n2"))]
    if third:
        placements.append(("economy", ("e1", "e1", "e2")))
    design = {
        "allocation_workload": [{"id": WORKLOAD}],
        "allocation_member": [{"id": member, "workload": WORKLOAD, "cpu": 2, "memory": 8, "disk": 80}
                              for member in members],
        "allocation_scope": [{"id": SCOPE}, {"id": "other-order"}],
        "reference_date": [{"id": "comparison-day", "title": DAY, "day": 20260115}],
        "allocation_comparison": [{"id": "comparison-cut", "workload": WORKLOAD, "scope": SCOPE,
                                  "reference_date": "comparison-day"}],
        "allocation_candidate_coverage": (
            [{"id": "alternatives-cut", "comparison": "comparison-cut"}] if complete_candidates else []),
        "allocation_candidate": [{"id": name, "workload": WORKLOAD, "scope": SCOPE,
                                 "placement": "physical" if name == "physical" else "nested"}
                                for name, _ in placements],
        "allocation_assignment": [{"id": f"{candidate}-{member}", "candidate": candidate,
                                   "member": member, "host": host}
                                  for candidate, hosts in placements
                                  for member, host in zip(members, hosts, strict=True)],
    }
    suppliers = {"allocation_host": [], "allocation_charge": [], "allocation_supplier_limit": [
        {"id": "order-limit", "scope": SCOPE, "supplier": "supplier-one",
         "stock": 5, "account_limit": account_limit, "plan_limit": 4},
    ]}
    for candidate, hosts in placements:
        for host in sorted(set(hosts)):
            capacity = {"id": host, "supplier": "supplier-one", "cpu": 8, "memory": 24}
            if not (missing_disk and host == "n1"):
                capacity["disk"] = 200
            suppliers["allocation_host"].append(capacity)
            if not setup:
                unit = {"physical": 400, "nested": 600, "economy": 550}[candidate]
                suppliers["allocation_charge"].append({"id": f"quote-{host}", "candidate": candidate,
                                                       "host": host, "currency": "EUR", "recurring_minor": unit,
                                                       "setup_minor": 0, "periods": 1})
        if setup:
            recurring, once = {"physical": (100, 50), "nested": (120, 0)}[candidate]
            suppliers["allocation_charge"].append({"id": f"quote-{candidate}", "candidate": candidate,
                                                   "currency": "EUR", "recurring_minor": recurring,
                                                   "setup_minor": once, "periods": 1})

    approved = {
        "decision": [decision(f"approve-{resource}") for resource in ("cpu", "memory", "disk")],
        "allocation_reserve": [{"id": f"reserve-{resource}", "decision": f"approve-{resource}",
                                "scope": SCOPE, "resource": resource, "amount": amount}
                               for resource, amount in (("cpu", 1), ("memory", 4), ("disk", 40))],
        "allocation_preference": [],
        "allocation_preference_coverage": ([{"id": "preference-cut", "authority": AUTHORITY, "workload": WORKLOAD,
                                             "scope": coverage, "reference_date": "comparison-day"}] if coverage else []),
    }
    for name, stops, scope in preferences:
        previous = "prefer-physical" if supersedes and name == "prefer-nested" else None
        origin = decision(name, previous)
        if supersedes and name == "prefer-physical":
            origin["state"] = "superseded"
        approved["decision"].append(origin)
        approved["allocation_preference"].append({"id": f"term-{name}", "decision": name, "workload": WORKLOAD,
                                                  "scope": scope, "acceptable": list(stops)})
    return {"allocation-design.yaml": design, "allocation-supplier.yaml": suppliers,
            "allocation-decisions.yaml": approved}


def test_physical_nested_allocation(tmp_path):
    registered(QUESTION, __file__, "test_physical_nested_allocation")
    checked(PACK, tmp_path / "plain").question(QUESTION)
    prefix = (WORKLOAD, SCOPE)
    physical = ("prefer-physical", PHYSICAL, SCOPE)
    nested = ("prefer-nested", NESTED, SCOPE)

    def compare(name, preferences, winner=None, status=None, **changes):
        publication = checked(PACK, tmp_path / name, recorded_allocation(preferences, **changes))
        relation = publication.question(QUESTION)
        assert publication.rows(relation) == ({prefix + (winner,)} if winner else set())
        assert publication.rows("allocation_comparison_status") == ({prefix + (status,)} if status else set())
        return publication, relation

    tied, relation = compare("one-physical", (physical,), "physical")
    assert tied.rows("allocation_payable_total") == {prefix + ("physical", "EUR", "1200"),
                                                   prefix + ("nested", "EUR", "1200")}
    assert {"prefer-physical", "preference-cut", "alternatives-cut"} <= tied.ground_ids(relation, prefix + ("physical",))
    compare("one-nested", (nested,), "nested")
    for name, preferences in (("conflict", (physical, nested)), ("reverse-conflict", (nested, physical))):
        report, _ = compare(name, preferences, status="ambiguous_preference")
        finding = prefix + ("ambiguous_preference",)
        assert {"prefer-physical", "prefer-nested", "preference-cut"} <= report.ground_ids(
            "allocation_comparison_status", finding)
    compare("agreement", (physical, ("also-physical", PHYSICAL, SCOPE)), "physical")
    compare("multiple", (("both", ("physical", "nested"), SCOPE),), status="ambiguous_preference")
    compare("no-acceptable-candidate", (("neither", (), SCOPE),), status="ambiguous_preference")
    replaced, relation = compare("successor", (physical, nested), "nested", supersedes=True)
    assert ("decision__supersedes", ("prefer-nested", "prefer-physical")) in replaced.ground_keys(
        relation, prefix + ("nested",))
    missing, _ = compare("absent", (), status="missing_preference")
    assert "preference-cut" in missing.ground_ids("allocation_comparison_status", prefix + ("missing_preference",))
    compare("partial-register", (physical,), status="unknown", coverage=None)
    compare("wrong-register", (physical,), status="unknown", coverage="other-order")
    compare("different-scope", (physical, ("other-nested", NESTED, "other-order")), "physical")
    compare("strictly-cheaper", (physical,), "economy", third=True)
    setup, _ = compare("setup-charge", (physical,), "nested", setup=True)
    assert setup.rows("allocation_payable_total") == {prefix + ("physical", "EUR", "150"),
                                                    prefix + ("nested", "EUR", "120")}
    compare("account-limit", (physical,), "nested", account_limit=2)
    compare("missing-disk", (physical,), status="unknown", missing_disk=True)
    compare("missing-inventory", (physical,), status="unknown", complete_candidates=False)

    for reserve, feasible in ((39, True), (40, True), (41, False)):
        change = {"op": "set", "kind": "allocation_reserve", "key": "reserve-disk",
                  "slot": "amount", "value": reserve}
        report = checked(PACK, tmp_path / f"disk-{reserve}", recorded_allocation((nested,)), change=change)
        chosen = report.question(QUESTION)
        assert report.rows(chosen) == {prefix + (("nested" if feasible else "physical"),)}
        failure = prefix + ("nested", "n1", "disk")
        assert (failure in report.rows("allocation_limit_exceeded")) is (not feasible)
        if not feasible:
            assert {"member-one", "member-two", "reserve-disk", "approve-disk", "n1"} <= report.ground_ids(
                "allocation_limit_exceeded", failure)
