"""Map a recorded order status to the run's order outcome, per decisions/run-price-enforcement.md."""

import pytest

from offline_cases import implementation


@pytest.mark.xfail(strict=True, reason=(
    "Read decisions/run-price-enforcement.md, Correlation. Implement outcome(body) in run/ovh_order_status.py: "
    "the raw JSON body of the order status read becomes one outcome."
))
def test_ovh_order_status():
    outcome = implementation("ovh_order_status.py", "outcome")

    expected = {
        b'"notPaid"': "not_committed",
        b'"checking"': "pending",
        b'"documentsRequested"': "pending",
        b'"delivering"': "pending",
        b'"delivered"': "delivered",
        b'"cancelled"': "refused",
        # Unknown is explicit: never read a doubtful status as delivered or as refused.
        b'"cancelling"': "unresolved",
        b'"unknown"': "unresolved",
        b'"Delivered"': "unresolved",
        b'"paid"': "unresolved",
        b'null': "unresolved",
        b'["delivered"]': "unresolved",
        b'{"status": "delivered"}': "unresolved",
        b'': "unresolved",
        b'"delivered': "unresolved",
    }
    assert {body: outcome(body) for body in expected} == expected
