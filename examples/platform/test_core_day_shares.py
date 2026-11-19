"""Compare the platform's actual DuckDB result with an independent daily ledger."""
from datetime import date
from fractions import Fraction
from pathlib import Path

import pytest

from rezono_compiler import facts, pack, rules
from request_preview import relation_rows

ROOT = Path(__file__).resolve().parent
DAY = date(2026, 3, 1).toordinal()
MARCH = (0, 31)
JANUARY = (-59, -28)
# An upstream observation, an in-month resize and disappearance, and an open interval.
OBS = [("a", "lake", "ivy", -3, 2), ("b", "lake", "ivy", 3, 5),
       ("c", "lake", "ivy", 7, 0), ("d", "ridge", "larch", 26, 3)]


def shares(events, lo, hi, cost, *, coverage=()):
    if not any(start <= lo and hi <= end for start, end in coverage):
        return None
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
    assert shares(OBS, *MARCH, 107, coverage=(MARCH,)) == {
        "ivy": (26, Fraction(2782, 41)), "larch": (15, Fraction(1605, 41)),
    }
    resized = [(*row[:4], 4 if row[0] == "b" else row[4]) for row in OBS]
    assert shares(resized, *MARCH, 107, coverage=(MARCH,))["ivy"] == (22, Fraction(2354, 37))


def test_daily_oracle_charges_the_platform_for_a_proven_empty_month():
    assert shares(OBS, *JANUARY, 103, coverage=(JANUARY, MARCH)) == {"platform": (0, Fraction(103))}


def test_daily_oracle_leaves_unmeasured_month_unknown():
    assert shares(OBS, -59, -28, 103) is None
    assert shares(OBS, *JANUARY, 103, coverage=(MARCH,)) is None


@pytest.mark.parametrize("partial", [(-58, -28), (-59, -29)])
def test_daily_oracle_leaves_a_partly_measured_month_unknown(partial):
    assert shares(OBS, *JANUARY, 103, coverage=(partial, MARCH)) is None


class MissingShareRules(AssertionError):
    pass


@pytest.mark.xfail(
    strict=True,
    raises=MissingShareRules,
    reason="extra: Implement covered shared-cost shares and balance in examples/platform/rules/shared_cost.dl "
           "with inputs in schema/shared_cost.yaml. Read decisions/platform-core-day-shares.md. "
           "Waits for exact reduced fraction support in rule relations: rules reject data-dependent divisors "
           "and the calculation bridge only exposes known whole numbers. The balance has to sum derived shares.",
)
def test_monthly_shares_and_balance_follow_observations():
    model = pack.read(ROOT)
    required = {"shared_cost_share", "shared_cost_balance"}
    program = rules.load(model.rules)
    if not required <= set(program.derived()):
        raise MissingShareRules("the platform lacks observed core-day shares or their independent balance")
    assert program.reaches("shared_cost_share", "shared_cost_balance"), "balance must depend on actual shares"
    cases = [
        (5, 107, (JANUARY,)),
        (4, 107, (JANUARY,)),
        (5, 109, (JANUARY,)),
        (5, 107, ()),
        (5, 107, ((-58, -28),)),
        (5, 107, ((-59, -29),)),
    ]
    for resize, price, january_coverage in cases:
        events = [(*row[:4], resize if row[0] == "b" else row[4]) for row in OBS]
        months = [("march", *MARCH, price), ("january", *JANUARY, 103)]
        coverage = (MARCH, *january_coverage)
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
                "observed_delivery_coverage": [dict(id=f"inventory/{lo}/{hi}", start_day=DAY+lo, end_day=DAY+hi)
                                               for lo, hi in coverage],
            })
            actual = sorted(relation_rows(model, inputs, "shared_cost_share"))
            balance = sorted(relation_rows(model, inputs, "shared_cost_balance"))
            expected = []
            totals = []
            for m, lo, hi, c in months:
                ledger = shares(events, lo, hi, c, coverage=coverage)
                if ledger is None:
                    continue
                expected.extend((m, t, days, frac.numerator, frac.denominator)
                                for t, (days, frac) in ledger.items())
                total = sum((Fraction(n, d) for month, _, _, n, d in actual if month == m), Fraction())
                assert total == c
                totals.append((m, total.numerator, total.denominator))
            assert actual == sorted(expected)
            assert balance == sorted(totals)
