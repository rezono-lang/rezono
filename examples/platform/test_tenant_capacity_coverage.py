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
SOURCE, RECEIPT, TAG = "capacity-readings", "receipt-capacity", "capacity-reading"


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
    """Admitted rows of one receipt. Each member key is [tag, period, tenant]: the tag that names an expected
    reading, the period the rule joins on, then the tenant (decisions/admission-transport.md section 6)."""
    member_rows = []
    for member in members:
        key = json.dumps(list(member), separators=(",", ":"))
        member_rows += [(RECEIPT, key, part, value) for part, value in enumerate(member)]
    return {"verified_receipt": [(RECEIPT, source, "capacity-scope", "capacity-cut", "1" * 64, "2" * 64)],
            "verified_member": member_rows}


@pytest.mark.xfail(strict=True, raises=FreeCapacityWithoutCoverage, reason=(
    "M2: decisions/scoped-completeness.md: Declare verified_receipt and verified_member in "
    "examples/platform/rules/tenant_capacity.dl, derive platform_capacity_basis only for a period that a verified "
    "receipt from the source 'capacity-readings' covers with a reading for every member, and derive "
    "platform_capacity_unknown(period, reason, subject) with 'coverage-missing' or 'reading-missing' otherwise. "
    "A member is the key [\"capacity-reading\", period, tenant] (decisions/admission-transport.md section 6, "
    "member keys): read only members whose part 0 is 'capacity-reading', with the period in part 1 and the "
    "tenant in part 2."))
def test_free_capacity_needs_verified_coverage_of_the_readings():
    model = pack.read(ROOT)
    rows = readings(model)
    basis = relation_rows(model, rows, BASIS)
    if basis:
        raise FreeCapacityWithoutCoverage(f"free capacity without coverage of the readings: {basis}")
    assert relation_rows(model, rows, UNKNOWN) == [("early", "coverage-missing", "early"),
                                                   ("late", "coverage-missing", "late")]

    everyone = [(TAG, period, team) for period, (_, used_by) in PERIODS.items() for team in used_by]
    covered = rows | receipt(everyone)
    assert relation_rows(model, covered, BASIS) == [("early", 3, 8), ("late", 7, 10)]
    assert relation_rows(model, covered, UNKNOWN) == []

    # A member under another tag belongs to another scope: it asks for no reading here.
    tagged = rows | receipt([*everyone, ("other-scope", "late", "absent")])
    assert relation_rows(model, tagged, BASIS) == [("early", 3, 8), ("late", 7, 10)]
    assert relation_rows(model, tagged, UNKNOWN) == []

    # The receipt says a third tenant had to be read in the late period; without its reading late is unknown.
    missing = rows | receipt([*everyone, (TAG, "late", "absent")])
    assert relation_rows(model, missing, BASIS) == [("early", 3, 8)]
    assert relation_rows(model, missing, UNKNOWN) == [("late", "reading-missing", "absent")]

    # A receipt of another source covers nothing here.
    foreign = rows | receipt(everyone, source="other-register")
    assert relation_rows(model, foreign, BASIS) == []
    assert relation_rows(model, foreign, UNKNOWN) == [("early", "coverage-missing", "early"),
                                                      ("late", "coverage-missing", "late")]
