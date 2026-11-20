"""Block an order whose paid service could renew or outlast its bound, per decisions/run-price-enforcement.md."""

import pytest

from offline_cases import implementation

DEADLINE = "2032-05-04T22:00:00Z"


def service(**changes):
    renew = {"automatic": False, "forced": False, "deleteAtExpiration": True, "manualPayment": False, "period": 1}
    body = {"serviceId": 9, "domain": "srv-1.example.org", "status": "ok", "creation": "2032-05-04",
            "expiration": "2032-06-03", "engagedUpTo": None, "renewalType": "manual", "renew": renew}
    for key, value in changes.items():
        if key in renew:
            renew[key] = value
        else:
            body[key] = value
    return body


def test_ovh_renewal():
    blocks = implementation("ovh_renewal.py", "blocks")

    assert blocks(service(), DEADLINE) == []
    assert blocks(service(engagedUpTo="2032-06-03"), DEADLINE) == []
    assert blocks(service(automatic=True), DEADLINE) == ["renews_automatically"]
    assert blocks(service(forced=True), DEADLINE) == ["renewal_forced"]
    assert blocks(service(deleteAtExpiration=False), DEADLINE) == ["not_deleted_at_expiration"]
    assert blocks(service(automatic=True, deleteAtExpiration=False), DEADLINE) == [
        "not_deleted_at_expiration", "renews_automatically"]
    assert blocks(service(engagedUpTo="2032-07-03"), DEADLINE) == ["engaged_beyond_expiration"]
    # The expiration date counts from its UTC midnight; equality with the deadline blocks.
    assert blocks(service(), "2032-06-02T23:59:59Z") == []
    assert blocks(service(), "2032-06-03T00:00:00Z") == ["period_ends_before_deadline"]
    assert blocks(service(), "2032-06-03T01:00:00+01:00") == ["period_ends_before_deadline"]
    # Missing or ill-typed evidence is unknown, never bounded.
    assert blocks(service(expiration=None), DEADLINE) == ["expiration_unknown"]
    assert blocks(service(automatic=None), DEADLINE) == ["renewal_unknown"]
    assert blocks(service(deleteAtExpiration="true"), DEADLINE) == ["renewal_unknown"]
    assert blocks({k: v for k, v in service().items() if k != "renew"}, DEADLINE) == ["renewal_unknown"]
    with pytest.raises(ValueError):
        blocks(service(), "2032-05-04T22:00:00")
