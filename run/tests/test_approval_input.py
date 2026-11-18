import pytest

from input_contract_cases import DIGEST, verify


def test_bounded_approval_shape():
    base = dict(plan_hash=DIGEST, budget_cents=0, currency="EUR",
                expires_at="2030-01-01T00:00:00Z", decision="approve")
    bad = [
        dict(plan_hash=DIGEST + "\n"), dict(plan_hash="A" * 64),
        dict(budget_cents=-1), dict(budget_cents=True), dict(budget_cents=0.5),
        dict(currency="eur"), dict(currency="EUR\n"), dict(extra="field"),
        dict(expires_at="2030-02-30T00:00:00Z"), dict(expires_at="2030-01-01T00:00:00+00:00"),
        dict(decision=True), dict(decision="pending"),
    ]
    verify("approval.json", [base, base | dict(decision="decline", budget_cents=12)],
           [base | patch for patch in bad])
