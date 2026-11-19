"""Reconcile independently recorded sides per decisions/run-reconciliation.md."""

from datetime import datetime

import pytest

from checked_questions import MissingReaderQuestion, checked, registered
from rezono_canon import canonical_sha256


PACK, QUESTION = "invoice-drift", "run-reconciliation"
PROFILE, RUN = "sample", "recorded-run"
DAY = "2026-01-15"
SCOPE = (PROFILE, RUN)


def instant(time):
    return int(datetime.fromisoformat(f"{DAY}T{time}:00+00:00").timestamp())


def interval(identity, start, end):
    value = {"id": identity, "on_axis": "utc-seconds", "start": instant(start)}
    if end is not None:
        value["end"] = instant(end)
    return value


def inputs(*, second_stop="03:00", registry=True, invoice=True, cap=300, billed_cap=None, registry_a=50,
           matched=False):
    forecast = {
        "reconciliation_plan": [{"id": "approved-plan", "profile": PROFILE, "window": "planned-window",
                                 "reference_date": "comparison-day"}],
        "reconciliation_plan_window": [interval("planned-window", "00:00", "02:00")],
        "reconciliation_planned_line": [{"id": f"planned-{slot}", "plan": "approved-plan",
                                         "slot": slot, "supplier_plan": "plan-a", "quantity": 1}
                                        for slot in ("first", "second")],
    }
    plan_hash = canonical_sha256(forecast)
    forecast["reconciliation_plan"][0]["sha256"] = plan_hash
    quote = {
        "reconciliation_quote": [{"id": "forecast-quote", "supplier_plan": "plan-a", "hourly_minor": 45,
                                  "currency": "EUR", "reference_date": "comparison-day"}],
    }
    measured = {
        "reference_date": [{"id": "comparison-day", "title": DAY, "day": 20260115}],
        "axis": [{"id": "utc-seconds"}],
        "reconciliation_run": [{"id": RUN, "profile": PROFILE, "plan": "approved-plan",
                                "window": "run-window"}],
        "reconciliation_run_window": [interval("run-window", "00:00", "02:00" if matched else "03:00")],
        "reconciliation_activity": [
            interval("usage-a1", "00:00", "02:00" if matched else "03:00") | {"resource": "a1", "run": RUN},
            interval("usage-b1", "00:00", "02:00" if matched else second_stop) | {"resource": "b1", "run": RUN},
        ],
        "reconciliation_deployment": [
            {"id": "deployed-a1", "run": RUN, "resource": "a1", "supplier_plan": "plan-a"},
            {"id": "deployed-b1", "run": RUN, "resource": "b1", "supplier_plan": "plan-a" if matched else "plan-b"},
        ],
        "reconciliation_run_coverage": [{"id": "run-capture", "run": RUN}],
    }
    register_lines = [
        {"id": "registered-a1", "resource": "a1", "slot": "first", "supplier_plan": "plan-a", "quantity": 1,
         "hourly_minor": 45 if matched else registry_a, "currency": "EUR"},
        {"id": "registered-b1", "resource": "b1", "slot": "second", "supplier_plan": "plan-a" if matched else "plan-b",
         "quantity": 1, "hourly_minor": 45 if matched else 65, "currency": "EUR"},
    ]
    order = {
        "reconciliation_registry": [{"id": "order-capture", "run": RUN, "plan_hash": plan_hash,
                                     "captured_at": instant("04:00"), "sha256": canonical_sha256(register_lines)}],
        "reconciliation_registry_line": [line | {"registry": "order-capture"} for line in register_lines],
        "reconciliation_registry_coverage": [{"id": "order-coverage", "registry": "order-capture"}],
    }
    invoice_lines = [
        {"id": "billed-a1", "plan_hash": plan_hash, "item": "a1", "currency": "EUR", "minor": 90 if matched else 135},
        {"id": "billed-b1", "plan_hash": plan_hash, "item": "b1", "currency": "EUR", "minor": 90 if matched else 195},
    ]
    billing = {
        "invoice_line": invoice_lines,
        "reconciliation_invoice_coverage": [{"id": "invoice-capture", "run": RUN,
                                             "lines": ["billed-a1", "billed-b1"],
                                             "sha256": canonical_sha256(invoice_lines)}],
    }
    terms = [{"id": "decision-usage-terms", "title": "Usage", "decider": ["run-authority"],
              "decided_on": DAY, "valid_from": DAY, "valid_from_day": 20260115, "state": "in_force"}]
    spending = []
    for basis, amount in (("rated", cap), ("billed", billed_cap)):
        if amount is not None:
            identity = f"decision-cap-{basis}"
            terms.append({"id": identity, "title": identity, "decider": ["run-authority"],
                          "decided_on": DAY, "valid_from": DAY, "valid_from_day": 20260115, "state": "in_force"})
            spending.append({"id": f"cap-{basis}", "run": RUN, "basis": basis,
                             "decision": identity, "currency": "EUR", "minor": amount})
    approvals = {
        "decision": terms,
        "reconciliation_charge_terms": [{"id": "usage-terms", "run": RUN, "decision": "decision-usage-terms",
                                          "unit": "hour", "basis": "active_interval", "fee_minor": 0}],
        "reconciliation_ceiling": spending,
    }
    return {"approved-plan.yaml": forecast, "supplier-quote.yaml": quote, "recorded-run.yaml": measured,
            "order-registry.yaml": order if registry else {}, "order-invoice.yaml": billing if invoice else {},
            "reconciliation-decisions.yaml": approvals}


def test_run_reconciliation(tmp_path):
    registered(QUESTION, __file__, "test_run_reconciliation")
    checked(PACK, tmp_path / "plain").question(QUESTION)

    def replay(name, expected_amounts, *, elapsed="10800", **changes):
        report = checked(PACK, tmp_path / name, inputs(**changes))
        relation = report.question(QUESTION)
        assert report.rows(relation) == {SCOPE + (basis, "EUR", amount) for basis, amount in expected_amounts}
        duration = SCOPE + ("7200", elapsed)
        assert {"planned-window", "run-window"} <= report.ground_ids("reconciliation_duration", duration)
        return report, relation

    report, relation = replay("base", (("forecast", "180"), ("rated", "345"), ("billed", "330")))
    assert report.rows("reconciliation_usage_charge") == {SCOPE + ("a1", "EUR", "150"),
                                                         SCOPE + ("b1", "EUR", "195")}
    assert {"usage-a1", "usage-b1", "registered-a1", "registered-b1", "usage-terms"} <= report.ground_ids(
        relation, SCOPE + ("rated", "EUR", "345"))
    assert {"billed-a1", "billed-b1", "invoice-capture"} <= report.ground_ids(
        relation, SCOPE + ("billed", "EUR", "330"))
    assert {"planned-first", "planned-second", "forecast-quote", "planned-window"} <= report.ground_ids(
        relation, SCOPE + ("forecast", "EUR", "180"))
    departure = SCOPE + ("second", "plan-a", "plan-b")
    assert {"planned-second", "registered-b1"} <= report.ground_ids("reconciliation_plan_difference", departure)
    rate = SCOPE + ("plan-a", "EUR", "45", "50")
    assert {"forecast-quote", "registered-a1"} <= report.ground_ids("reconciliation_rate_difference", rate)
    assert {"facts/supplier-quote.yaml", "facts/order-registry.yaml"} <= report.ground_files(
        "reconciliation_rate_difference", rate)
    assert {"facts/approved-plan.yaml", "facts/recorded-run.yaml"} <= report.ground_files(
        "reconciliation_duration", SCOPE + ("7200", "10800"))
    overrun = SCOPE + ("rated", "EUR", "345", "300", "45")
    assert {"decision-cap-rated", "usage-b1", "registered-b1"} <= report.ground_ids("reconciliation_cap_overrun", overrun)

    short, _ = replay("short-usage", (("forecast", "180"), ("rated", "215"), ("billed", "330")), second_stop="01:00")
    assert short.rows("reconciliation_usage_charge") == {SCOPE + ("a1", "EUR", "150"),
                                                        SCOPE + ("b1", "EUR", "65")}
    assert short.rows("reconciliation_rate_difference") == {rate}
    assert short.rows("reconciliation_cap_overrun") == set()
    assert short.rows("reconciliation_cap_result") == {SCOPE + ("rated", "EUR", "215", "300", "0")}

    incomplete, _ = replay("missing-stop", (("forecast", "180"), ("billed", "330")), second_stop=None)
    assert SCOPE + ("rated", "unknown") in incomplete.rows("reconciliation_status")
    assert not incomplete.rows("reconciliation_cap_overrun")

    ratings = (("forecast", "180"), ("rated", "345"), ("billed", "330"))
    divided, _ = replay("separate-ceilings", ratings, cap=340, billed_cap=340)
    rated = SCOPE + ("rated", "EUR", "345", "340", "5")
    billed = SCOPE + ("billed", "EUR", "330", "340", "0")
    assert divided.rows("reconciliation_cap_overrun") == {rated}
    assert divided.rows("reconciliation_cap_result") == {rated, billed}
    assert {"decision-cap-billed", "billed-a1", "billed-b1"} <= divided.ground_ids("reconciliation_cap_result", billed)

    unknown_invoice, _ = replay("missing-invoice", ratings[:2], invoice=False, cap=340, billed_cap=340)
    assert unknown_invoice.rows("reconciliation_cap_overrun") == {rated}
    assert {SCOPE + ("billed", "unknown"), SCOPE + ("billed_cap", "unknown")} <= unknown_invoice.rows(
        "reconciliation_status")
    unknown_registry, _ = replay("missing-registry", (ratings[0], ratings[2]), registry=False)
    assert SCOPE + ("rated", "unknown") in unknown_registry.rows("reconciliation_status")
    assert unknown_registry.rows("reconciliation_rate_difference") == set()

    changed_rate, _ = replay("changed-rate", (("forecast", "180"), ("rated", "360"), ("billed", "330")), registry_a=55)
    assert changed_rate.rows("reconciliation_rate_difference") == {SCOPE + ("plan-a", "EUR", "45", "55")}
    unknown_ceiling, _ = replay("missing-cap", ratings, cap=None)
    assert SCOPE + ("rated_cap", "unknown") in unknown_ceiling.rows("reconciliation_status")
    assert unknown_ceiling.rows("reconciliation_cap_result") == set()

    matched, _ = replay("matched", (("forecast", "180"), ("rated", "180"), ("billed", "180")),
                        elapsed="7200", matched=True)
    assert matched.rows("reconciliation_rate_difference") == matched.rows("reconciliation_plan_difference") == set()
