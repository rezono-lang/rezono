"""Derive a claim release plan only from an ended lease and a complete empty pull reading."""
import hashlib
from pathlib import Path

import pytest
import yaml
from test_build_selection import OBSERVED_AT, capture, published, repository

ROOT = Path(__file__).resolve().parents[2]
LEASE = 4 * 60 * 60
KINDS = {"BuildClaim", "BuildClaimActivity", "BuildClaimLease", "BuildClaimPullReading"}
# capture() supplies the run's receipt "receipt" at OBSERVED_AT. A `none` reading names the receipt that attests
# its complete read (decisions/build-claim-release.md section 1). These two attest nothing for this run and cut.
CLAIM_RECEIPTS = [
    {"id": "foreign-round", "run": "other", "event_time": OBSERVED_AT},
    {"id": "stale-round", "run": "current", "event_time": OBSERVED_AT - 1},
]


def declared_kinds():
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def generation(name):
    return hashlib.sha1(name.encode("utf-8")).hexdigest()


def claim_records(leases):
    """Hand-worked cases, one failing ground each, against the Delete guard of formal/Claims.tla."""
    t = OBSERVED_AT
    cases = {
        # branch: (observed_at, pushed generation, pushed_at, pull readings as (tick, state[, receipt]))
        # A `none` reading names the run's receipt at its tick unless the case names another or None.
        "task/expired": (t, None, t - LEASE, [(t, "none")]),
        "task/active": (t, None, t - LEASE + 1, [(t, "none")]),
        "task/renewed": (t, "task/renewed-before", t - 10 * LEASE, [(t, "none")]),
        "task/open": (t, None, t - LEASE, [(t, "open")]),
        "task/unread": (t, None, t - LEASE, []),
        "task/contradicted": (t, None, t - LEASE, [(t, "none"), (t, "open")]),
        "task/old-reading": (t, None, t - LEASE, [(t - 1, "none", "stale-round")]),
        "task/unattested": (t, None, t - LEASE, [(t, "none", None)]),
        "task/foreign-receipt": (t, None, t - LEASE, [(t, "none", "foreign-round")]),
        "task/stale-receipt": (t, None, t - LEASE, [(t, "none", "stale-round")]),
        "task/earlier-listing": (t - 1, None, t - 10 * LEASE, [(t, "none")]),
    }
    records = {
        "reference_date": [{"id": "policy-day", "title": "Observed reference day",
                            "date": "2027-01-15", "day": 20270115}],
        "build_policy_date": [{"id": "policy-cut", "run": "current", "reference": "policy-day", "observed_at": t}],
        "decision": [
            {"id": f"lease-{index}", "title": f"Claim lease {index}", "state": "in_force",
             "valid_from": "2027-01-01", "valid_from_day": 20270101, "decider": ["build-policy"]}
            for index, _ in enumerate(leases)
        ],
        "build_claim_lease": [
            {"id": f"lease-{index}-duration", "decision": f"lease-{index}", "seconds": seconds}
            for index, seconds in enumerate(leases)
        ],
        "build_claim": [], "build_claim_activity": [], "build_claim_pull_reading": [],
    }
    for branch, (observed_at, pushed, pushed_at, readings) in cases.items():
        records["build_claim"].append({"id": branch, "run": "current", "branch": branch,
                                       "generation": generation(branch), "observed_at": observed_at,
                                       "source": "ref-listing"})
        after = generation(pushed or branch)
        records["build_claim_activity"].append({"id": f"{branch}@{after}", "claim": branch, "after": after,
                                                "pushed_at": pushed_at, "source": "push-activity"})
        for tick, state, *named in readings:
            receipt = (named or ["receipt"])[0] if state == "none" else None
            records["build_claim_pull_reading"].append(
                {"id": f"{branch}@{tick}-{state}", "claim": branch, "observed_at": tick, "state": state,
                 "source": "pull-query", **({"receipt": receipt} if receipt else {})}
            )
    return records


@pytest.mark.parametrize(("leases", "policy_known"), [([LEASE], True), ([LEASE, 2 * LEASE], False), ([], False)])
def test_build_claim_release_plan(tmp_path, leases, policy_known):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    records = capture(source, base, head, paths)
    records.update(claim_records(leases))
    records["loop_sweep_receipt"].extend(CLAIM_RECEIPTS)
    rows = published(tmp_path, records)
    plans = {tuple(row["key"][:3]) for row in rows.get("build_claim_release_plan", [])}
    held = {tuple(row["key"][:3]) for row in rows.get("build_claim_held", [])}

    if not policy_known:
        assert plans == set(), f"A claim was released without one lease duration in force: {plans}"
        assert {claim for _, claim, reason in held if reason == "lease-policy-unknown"} == {
            "task/expired", "task/active", "task/renewed", "task/open", "task/unread", "task/contradicted",
            "task/old-reading", "task/unattested", "task/foreign-receipt", "task/stale-receipt",
        }
        return

    assert plans == {("current", "task/expired", generation("task/expired"))}, (
        f"Only the ended, unopened lease at the cut may be planned for release: {plans}"
    )
    assert all(row["key"][3] for row in rows["build_claim_release_plan"]), "A plan must retain its reason"
    assert held == {
        ("current", "task/active", "lease-active"),
        ("current", "task/renewed", "lease-unknown"),
        ("current", "task/open", "pull-request-open"),
        ("current", "task/unread", "pull-request-unknown"),
        ("current", "task/contradicted", "pull-request-open"),
        ("current", "task/old-reading", "pull-request-unknown"),
        ("current", "task/unattested", "pull-request-unknown"),
        ("current", "task/foreign-receipt", "pull-request-unknown"),
        ("current", "task/stale-receipt", "pull-request-unknown"),
    }, f"Each held claim must name exactly its own missing ground: {held}"
