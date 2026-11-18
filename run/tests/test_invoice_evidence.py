from fractions import Fraction
from hashlib import sha256

import pytest

from offline_cases import implementation, relation


PLAN = sha256(b"priced synthetic order").hexdigest()
OTHER = sha256(b"separate synthetic order").hexdigest()


def terms(mode):
    body = ('{"currency":"EUR","minor_per_unit":100,"boundary":"line","mode":"' + mode + '"}').encode()
    return {"url": "https://billing.example.org/terms", "sha256": sha256(body).hexdigest(), "body": body}


def cost(item, amount):
    return {"plan_hash": PLAN, "item": item, "currency": "EUR", "expected": amount, "ref": "cost/" + item}


def invoice(item, cents, ref, plan=PLAN):
    return {"plan_hash": plan, "item": item, "currency": "EUR", "observed_minor": cents, "ref": ref}


EXPECTED = [cost("rental", [5, 8]), cost("setup", [1, 8])]
MATCH = [invoice("rental", 63, "invoice/1"), invoice("setup", 13, "invoice/2")]
WRONG = [invoice("rental", 64, "invoice/1"), invoice("setup", 12, "invoice/2")]


def test_invoice_evidence_reference():
    exact = [100 * Fraction(*row["expected"]) for row in EXPECTED]
    half_up = [(2 * x.numerator + x.denominator) // (2 * x.denominator) for x in exact]
    assert half_up == [63, 13]
    assert [round(x) for x in exact] == [62, 12]
    observed = [row["observed_minor"] for row in WRONG]
    assert sum(half_up) == sum(observed) and [a - b for a, b in zip(observed, half_up)] == [1, -1]


def test_invoice_evidence():
    normalize = implementation("invoice_compare.py", "invoice_facts")

    def compare(observations, policy):
        facts = normalize(EXPECTED, observations, policy)
        return (relation("invoice-drift", facts, "amount_difference"),
                relation("invoice-drift", facts, "unbound_invoice"))

    up = terms("half_up")
    assert compare(MATCH, up) == (set(), set())
    orphans = [invoice("rental", 63, "invoice/3", None), invoice("extra", 1, "invoice/4"),
               invoice("rental", 63, "invoice/5", OTHER)]
    expected = {(PLAN, "rental", "cost/rental", "invoice/1", up["sha256"], "63", "64"),
                (PLAN, "setup", "cost/setup", "invoice/2", up["sha256"], "13", "12")}
    assert compare(WRONG + orphans, up) == (expected, {("invoice/3", "missing_plan"),
                                                       ("invoice/4", "unmatched_item"),
                                                       ("invoice/5", "unmatched_item")})
    even = terms("half_even")
    assert compare(MATCH, even) == (
        {(PLAN, "rental", "cost/rental", "invoice/1", even["sha256"], "62", "63"),
         (PLAN, "setup", "cost/setup", "invoice/2", even["sha256"], "12", "13")}, set())
    with pytest.raises(ValueError):
        normalize(EXPECTED, MATCH, dict(up, body=even["body"]))
