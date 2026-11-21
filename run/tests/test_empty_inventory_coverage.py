"""Empty provider inventory requires provable, fresh, account-wide coverage before concluding absence.

Per decisions/admission-transport.md, decisions/scoped-completeness.md, decisions/code-does-not-decide.md,
and decisions/run-price-enforcement.md ("Cleanup"), an empty server listing (`[]`) may establish absence
only when the cleanup pack derives `listing_absent` from an unfiltered account-wide request bound to the
expected account scope and a measurement timestamp strictly after the freshness boundary. The exact same
empty response with unknown/missing/mismatched scope, missing or stale timestamp, filtered request, or
non-complete coverage must yield `unknown` with an explicit reason from `listing_absence_unknown`.
"""

from runpy import run_path

import pytest

from offline_cases import RUN

DELIVERED = ["srv-2.example.org", "srv-1.example.org"]
EMPTY_LISTING = b"[]"
EXPECTED_REQUEST = ("GET", "/dedicated/server")
EXPECTED_SCOPE = "account-one"
FRESH_AFTER_US = 100


def _pack_reads(monkeypatch):
    """Record `(pack, relation, rows)` read through `rezono_compiler.batch.read`."""
    from rezono_compiler import batch

    reads = []
    original = batch.read

    def spy(connection, program, names=None):
        rows = original(connection, program, names)
        for name, values in rows.items():
            reads.append((program.pack, name, set(values)))
        return rows

    monkeypatch.setattr(batch, "read", spy)
    return reads


def _latest_rows(reads, pack_name, relation_name):
    matches = [rows for pack, rel, rows in reads if (pack, rel) == (pack_name, relation_name)]
    assert matches, f"expected {(pack_name, relation_name)!r} to be read from batch.read; saw {reads!r}"
    return matches[-1]


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "M4: decisions/admission-transport.md: Stop fabricating complete unfiltered coverage for empty "
        "provider listings in run/ovh_inventory.py and derive explicit absence vs unknown coverage in "
        "run/packs/cleanup/rules/cleanup.dl (per decisions/scoped-completeness.md, "
        "decisions/code-does-not-decide.md, and decisions/run-price-enforcement.md). Export "
        "listing_absent(listing) and listing_absence_unknown(listing, reason) from run/packs/cleanup "
        "bound to the unfiltered request, account scope, complete coverage, and measurement timestamp "
        "strictly after fresh_after_us, and expose check_absence(listing, delivered, *, expected_scope, "
        "fresh_after_us, evidence) in run/ovh_inventory.py reading those derived rows."
    ),
)
def test_empty_provider_inventory_requires_proven_coverage(monkeypatch):
    from rezono_compiler import pack, rules

    program = rules.load(pack.read(RUN / "packs" / "cleanup").rules)
    derived = set(program.derived())
    assert {"listing_absent", "listing_absence_unknown"} <= derived, (
        f"run/packs/cleanup must derive listing_absent and listing_absence_unknown; found {sorted(derived)}"
    )

    module = run_path(str(RUN / "ovh_inventory.py"))
    assert "check_absence" in module, "run/ovh_inventory.py must expose check_absence for coverage-checked absence"
    check_absence = module["check_absence"]
    request = module["request"]
    assert request() == EXPECTED_REQUEST

    reads = _pack_reads(monkeypatch)

    # 1. Exact same empty response with fresh, provable, account-wide coverage -> absence allowed.
    valid_evidence = {
        "request": EXPECTED_REQUEST,
        "account_scope": EXPECTED_SCOPE,
        "observed_us": FRESH_AFTER_US + 1,
        "coverage": "complete",
        "unfiltered": True,
    }
    reads.clear()
    known_absent = check_absence(
        EMPTY_LISTING,
        DELIVERED,
        expected_scope=EXPECTED_SCOPE,
        fresh_after_us=FRESH_AFTER_US,
        evidence=valid_evidence,
    )
    assert known_absent == {
        "status": "absent",
        "known": True,
        "still_listed": [],
        "reason": None,
    }
    assert _latest_rows(reads, "cleanup", "listing_absent"), "expected listing_absent row for proven empty listing"
    assert _latest_rows(reads, "cleanup", "listing_absence_unknown") == set()

    # 2. Exact same empty response with unknown/missing/mismatched scope, missing/stale timestamp,
    #    filtered request, or incomplete coverage -> MUST yield unknown with explicit reason, never absent.
    unproven_cases = [
        ("missing-scope", dict(valid_evidence, account_scope=None)),
        ("empty-scope", dict(valid_evidence, account_scope="")),
        ("other-scope", dict(valid_evidence, account_scope="account-other")),
        ("missing-timestamp", dict(valid_evidence, observed_us=None)),
        ("stale-before-cutoff", dict(valid_evidence, observed_us=FRESH_AFTER_US - 1)),
        ("stale-at-cutoff", dict(valid_evidence, observed_us=FRESH_AFTER_US)),
        ("filtered-request", dict(valid_evidence, request=("GET", "/dedicated/server?tag=run-one"))),
        ("filtered-flag", dict(valid_evidence, unfiltered=False)),
        ("unknown-coverage", dict(valid_evidence, coverage="unknown")),
        ("incomplete-coverage", dict(valid_evidence, coverage="incomplete")),
    ]
    for label, evidence in unproven_cases:
        reads.clear()
        outcome = check_absence(
            EMPTY_LISTING,
            DELIVERED,
            expected_scope=EXPECTED_SCOPE,
            fresh_after_us=FRESH_AFTER_US,
            evidence=evidence,
        )
        assert outcome["status"] == "unknown", (label, outcome)
        assert outcome["known"] is False, (label, outcome)
        assert isinstance(outcome["reason"], str) and outcome["reason"].strip(), (label, outcome)
        assert _latest_rows(reads, "cleanup", "listing_absent") == set(), label
        unknown_rows = _latest_rows(reads, "cleanup", "listing_absence_unknown")
        assert unknown_rows, label
        assert outcome["reason"] in {reason for _, reason in unknown_rows}, (label, outcome, unknown_rows)

    # 3. Counter-case: non-empty listing with a delivered service still listed under valid coverage.
    reads.clear()
    still_present = check_absence(
        b'["other.example.org", "srv-1.example.org"]',
        DELIVERED,
        expected_scope=EXPECTED_SCOPE,
        fresh_after_us=FRESH_AFTER_US,
        evidence=valid_evidence,
    )
    assert still_present == {
        "status": "present",
        "known": True,
        "still_listed": ["srv-1.example.org"],
        "reason": None,
    }
    assert _latest_rows(reads, "cleanup", "listing_absent") == set()
    assert _latest_rows(reads, "cleanup", "listing_absence_unknown") == set()
    assert {service for _, service in _latest_rows(reads, "cleanup", "still_listed")} == {"srv-1.example.org"}
