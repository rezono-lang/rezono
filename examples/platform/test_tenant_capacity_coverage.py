"""Free capacity is known only when a verified receipt says which tenants the readings had to cover."""

import json
from pathlib import Path

import pytest

from rezono_compiler import facts, pack
from request_preview import relation_rows

ROOT = Path(__file__).resolve().parent
BASIS, UNKNOWN = "platform_capacity_basis", "platform_capacity_unknown"
# Period, pool cores, readings per tenant. The expectations below are computed by hand from these values.
PERIODS = {"early": (11, {"sprig": 3, "peer": 5}), "late": (17, {"sprig": 4, "peer": 6})}
SOURCE, RECEIPT = "capacity-readings", "receipt-capacity"


class FreeCapacityWithoutCoverage(AssertionError):
    pass


def readings(model):
    return facts.rows_of(model, {
        "role": [{"id": team, "title": team} for team in ("sprig", "peer", "absent")],
        "capacity_pool": [{"id": period, "cores": cores} for period, (cores, _) in PERIODS.items()],
        "capacity_reading": [{"id": f"{team}-{period}", "tenant": team, "period": period, "cores": used}
                             for period, (_, used_by) in PERIODS.items() for team, used in used_by.items()],
    })


def receipt(members, source=SOURCE):
    """Admitted rows of one receipt whose members are [period, tenant] keys of the expected readings."""
    member_rows = []
    for period, tenant in members:
        key = json.dumps([period, tenant], separators=(",", ":"))
        member_rows += [(RECEIPT, key, 0, period), (RECEIPT, key, 1, tenant)]
    return {"verified_receipt": [(RECEIPT, source, "capacity-scope", "capacity-cut", "1" * 64, "2" * 64)],
            "verified_member": member_rows}


@pytest.mark.xfail(strict=True, raises=FreeCapacityWithoutCoverage, reason=(
    "M2: decisions/scoped-completeness.md: Waits for "
    "edge/publisher/tests/test_completeness_publish.py--test_publisher_admits_receipts_only_with_a_trusted_context. "
    "Then declare verified_receipt and verified_member in examples/platform/rules/tenant_capacity.dl, derive "
    "platform_capacity_basis only for a period that a verified receipt from the source 'capacity-readings' covers "
    "with a reading for every member, and derive platform_capacity_unknown(period, reason, subject) with "
    "'coverage-missing' or 'reading-missing' otherwise. test_tenant_publication_proof.py then needs that receipt "
    "in its epochs (decisions/platform-tenant-proof-boundary.md)."))
def test_free_capacity_needs_verified_coverage_of_the_readings():
    model = pack.read(ROOT)
    rows = readings(model)
    basis = relation_rows(model, rows, BASIS)
    if basis:
        raise FreeCapacityWithoutCoverage(f"free capacity without coverage of the readings: {basis}")
    assert relation_rows(model, rows, UNKNOWN) == [("early", "coverage-missing", "early"),
                                                   ("late", "coverage-missing", "late")]

    everyone = [(period, team) for period, (_, used_by) in PERIODS.items() for team in used_by]
    covered = rows | receipt(everyone)
    assert relation_rows(model, covered, BASIS) == [("early", 3, 8), ("late", 7, 10)]
    assert relation_rows(model, covered, UNKNOWN) == []

    # The receipt says a third tenant had to be read in the late period; without its reading late is unknown.
    missing = rows | receipt([*everyone, ("late", "absent")])
    assert relation_rows(model, missing, BASIS) == [("early", 3, 8)]
    assert relation_rows(model, missing, UNKNOWN) == [("late", "reading-missing", "absent")]

    # A receipt of another source covers nothing here.
    foreign = rows | receipt(everyone, source="other-register")
    assert relation_rows(model, foreign, BASIS) == []
    assert relation_rows(model, foreign, UNKNOWN) == [("early", "coverage-missing", "early"),
                                                      ("late", "coverage-missing", "late")]
