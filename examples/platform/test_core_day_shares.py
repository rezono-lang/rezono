"""Compare the platform's actual DuckDB result with an independent daily ledger."""
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from rezono_compiler import facts, pack, rules
from request_preview import relation_rows

ROOT = Path(__file__).resolve().parent
DAY = date(2026, 3, 1).toordinal()
# An upstream observation, an in-month resize and disappearance, and an open interval.
OBS = [("a", "lake", "ivy", -3, 2), ("b", "lake", "ivy", 3, 5),
       ("c", "lake", "ivy", 7, 0), ("d", "ridge", "larch", 26, 3)]


def shares(events, lo, hi, cost):
    core_days = {}
    for day in range(lo, hi):
        latest = {}
        for _, delivery, owner, start, cores in sorted(events, key=lambda r: r[3]):
            if start <= day:
                latest[delivery] = owner, cores
        for owner, cores in latest.values():
            if cores:
                core_days[owner] = core_days.get(owner, 0) + cores
    total = sum(core_days.values())
    if not total:
        return {"platform": (0, Fraction(cost))}
    return {owner: (used, Fraction(cost * used, total)) for owner, used in core_days.items()}


def test_daily_oracle_examples():
    assert shares(OBS, 0, 31, 107) == {"ivy": (26, Fraction(2782, 41)), "larch": (15, Fraction(1605, 41))}
    assert shares(OBS, -59, -28, 103) == {"platform": (0, Fraction(103))}
    resized = [(*row[:4], 4 if row[0] == "b" else row[4]) for row in OBS]
    assert shares(resized, 0, 31, 107)["ivy"] == (22, Fraction(2354, 37))


class MissingShareRules(AssertionError):
    pass


@pytest.mark.xfail(strict=True, raises=MissingShareRules, reason="Implement the two shared-cost relations and their input schema in examples/platform/rules/shared_cost.dl and schema/shared_cost.yaml. Read decisions/platform-core-day-shares.md.")
def test_monthly_shares_and_balance_follow_observations():
    model = pack.read(ROOT)
    required = {"shared_cost_share", "shared_cost_balance"}
    program = rules.load(model.rules)
    if not required <= set(program.derived()):
        raise MissingShareRules("the platform lacks observed core-day shares or their independent balance")
    assert program.reaches("shared_cost_share", "shared_cost_balance"), "balance must depend on actual shares"
    for resize, price in [(5, 107), (4, 107), (5, 109)]:
        events = [(*row[:4], resize if row[0] == "b" else row[4]) for row in OBS]
        months = [("march", 0, 31, price), ("january", -59, -28, 103)]
        for ordered in (events, events[::-1]):
            inputs = facts.rows_of(model, {
                "tenant_service_request": [dict(id="juniper/unseen", tenant="juniper", service="unseen",
                                                profile="production", submitted_at="2026-03-01T00:00:00Z")],
                "tenant_request_item": [dict(id="juniper/unseen/cluster", tenant="juniper", service="unseen",
                                             item="cluster", size="medium")],
                "shared_monthly_cost": [dict(id=m, start_day=DAY+lo, end_day=DAY+hi, cents=c)
                                        for m, lo, hi, c in months],
                "observed_delivery_size": [dict(id=k, delivery=d, tenant=t, day=DAY+i, cores=n)
                                           for k, d, t, i, n in ordered],
            })
            actual = sorted(relation_rows(model, inputs, "shared_cost_share"))
            balance = sorted(relation_rows(model, inputs, "shared_cost_balance"))
            expected = []
            totals = []
            for m, lo, hi, c in months:
                ledger = shares(events, lo, hi, c)
                expected.extend((m, t, days, frac.numerator, frac.denominator)
                                for t, (days, frac) in ledger.items())
                total = sum((Fraction(n, d) for month, _, _, n, d in actual if month == m), Fraction())
                assert total == c
                totals.append((m, total.numerator, total.denominator))
            assert actual == sorted(expected)
            assert balance == sorted(totals)
