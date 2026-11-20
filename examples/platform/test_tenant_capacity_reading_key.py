"""A tenant has at most one capacity reading per period, so the platform basis never counts a tenant twice."""

import json
from pathlib import Path

from rezono_compiler import facts, pack
from request_preview import relation_rows
from support import compile_dir, violations

ROOT = Path(__file__).resolve().parent
KEY = "capacity_reading__tenant_period__unique"
SOURCE, RECEIPT, TAG = "capacity-readings", "receipt-capacity", "capacity-reading"


def readings(*observations):
    return facts.rows_of(pack.read(ROOT), {
        "role": [{"id": team, "title": team} for team in ("sprig", "peer")],
        "capacity_pool": [{"id": period, "cores": 11} for period in ("early", "late")],
        "capacity_reading": [{"id": f"{team}-{period}-{n}", "tenant": team, "period": period, "cores": cores}
                             for n, (team, period, cores) in enumerate(observations)],
    })


def receipt(*observations):
    """Verified coverage of the submitted readings, as decisions/admission-transport.md section 6 fixes."""
    members = sorted({(TAG, period, team) for team, period, _ in observations})
    member_rows = []
    for member in members:
        key = json.dumps(list(member), separators=(",", ":"))
        member_rows += [(RECEIPT, key, part, value) for part, value in enumerate(member)]
    return {"verified_receipt": [(RECEIPT, SOURCE, "capacity-scope", "capacity-cut", "1" * 64, "2" * 64)],
            "verified_member": member_rows}


def test_a_second_reading_of_one_tenant_in_one_period_is_refused(tmp_path):
    # Without the key, sprig's 3 cores measured twice summed to a basis of 6 used and 5 free.
    rows = readings(("sprig", "early", 3), ("sprig", "early", 3))
    assert violations(compile_dir(ROOT, tmp_path), rows) == {KEY: {("sprig-early-0", ""), ("sprig-early-1", "")}}


def test_readings_of_other_tenants_or_periods_are_accepted(tmp_path):
    observations = (("sprig", "early", 3), ("peer", "early", 5), ("sprig", "late", 4))
    rows = readings(*observations)
    assert violations(compile_dir(ROOT, tmp_path), rows) == {}
    assert relation_rows(pack.read(ROOT), rows | receipt(*observations), "platform_capacity_basis") == [
        ("early", 3, 8), ("late", 7, 4)]
