"""Read one plan's terms from a captured public catalog, per decisions/run-price-enforcement.md, The price list.

The expected fractions are the catalog's integer microcents divided by 10^8, computed by hand.
"""

from copy import deepcopy
from hashlib import sha256
import json

import pytest

from offline_cases import implementation


def pricing(capacity, price, tax, *, interval=1, unit="month", commitment=0, mode="default", kind="rental"):
    return {"capacities": [capacity], "commitment": commitment, "description": capacity, "interval": interval,
            "intervalUnit": unit, "mode": mode, "mustBeCompleted": False, "phase": 1, "price": price,
            "promotions": [], "quantity": {"max": 1, "min": 1}, "repeat": {"max": 1, "min": 1},
            "strategy": "tiered", "tax": tax, "type": kind}


def catalog():
    pricings = [
        pricing("installation", 4999000000, 999800000, interval=0, unit="none", kind="purchase"),
        pricing("renew", 8999000000, 1799800000),
        # A twelve-month commitment is a different offer and never a candidate.
        pricing("renew", 7999000000, 1599800000, commitment=12),
        pricing("renew", 9999000000, 1999800000, mode="upfront12"),
    ]
    return {"catalogId": 1, "locale": {"currencyCode": "EUR", "subsidiary": "FR", "taxRate": 20},
            "addons": [], "planFamilies": [], "products": [],
            "plans": [{"planCode": "example-plan", "pricingType": "rental", "pricings": pricings,
                       "family": "", "invoiceName": "Example", "product": "example", "addonFamilies": []},
                      {"planCode": "other-plan", "pricingType": "rental", "pricings": pricings[:2],
                       "family": "", "invoiceName": "Other", "product": "other", "addonFamilies": []}]}


def raw(value):
    return json.dumps(value).encode()


@pytest.mark.xfail(strict=True, reason=(
    "M4: decisions/run-price-enforcement.md: Read the section The price list. Implement terms(catalog, plan_code, mode) in "
    "run/ovh_catalog.py; catalog is the captured response body."
))
def test_ovh_catalog():
    terms = implementation("ovh_catalog.py", "terms")

    body = raw(catalog())
    assert terms(body, "example-plan", "default") == {
        "currency": "EUR", "setup": [4999, 100], "setup_tax": [4999, 500],
        "period": [8999, 100], "period_tax": [8999, 500], "interval_months": 1,
        "source_sha256": sha256(body).hexdigest(),
    }

    def blocked(change, plan="example-plan", mode="default"):
        value = catalog()
        change(value)
        with pytest.raises(ValueError):
            terms(raw(value), plan, mode)

    first = lambda value: value["plans"][0]["pricings"]  # noqa: E731
    # None or two valid candidates block.
    blocked(lambda value: first(value).append(deepcopy(first(value)[1])))
    blocked(lambda value: first(value).append(dict(deepcopy(first(value)[0]), price=5999000000)))
    blocked(lambda value: first(value).pop(0))
    blocked(lambda value: first(value).pop(1))
    blocked(lambda value: None, mode="hourly")
    blocked(lambda value: None, plan="missing-plan")
    blocked(lambda value: value["plans"].append(deepcopy(value["plans"][0])))
    # Usage billing has no bound; a period that is not one month is not the run's term.
    blocked(lambda value: first(value)[1].update(type="consumption"))
    blocked(lambda value: value["plans"][0].update(pricingType="consumption"))
    blocked(lambda value: first(value)[1].update(intervalUnit="day"))
    # Only exact integers count.
    blocked(lambda value: first(value)[1].update(price=89.99))
    blocked(lambda value: first(value)[1].update(price=True))
    blocked(lambda value: value["locale"].pop("currencyCode"))
