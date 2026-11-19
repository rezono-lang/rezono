"""Derive a claim release plan only from an ended lease and a complete empty pull reading."""
import hashlib
from pathlib import Path

import pytest
import yaml
from test_build_selection import OBSERVED_AT, capture, published, repository

ROOT = Path(__file__).resolve().parents[2]
LEASE = 4 * 60 * 60
KINDS = {"BuildClaim", "BuildClaimActivity", "BuildClaimLease", "BuildClaimPullReading"}


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
        # branch: (observed_at, pushed generation, pushed_at, pull readings as (tick, state))
        "task/expired": (t, None, t - LEASE, [(t, "none")]),
        "task/active": (t, None, t - LEASE + 1, [(t, "none")]),
        "task/renewed": (t, "task/renewed-before", t - 10 * LEASE, [(t, "none")]),
        "task/open": (t, None, t - LEASE, [(t, "open")]),
        "task/unread": (t, None, t - LEASE, []),
        "task/contradicted": (t, None, t - LEASE, [(t, "none"), (t, "open")]),
        "task/old-reading": (t, None, t - LEASE, [(t - 1, "none")]),
        "task/earlier-listing": (t - 1, None, t - 10 * LEASE, [(t, "none")]),
    }
    records = {
        "reference_date": [{"id": "policy-day", "title": "Observed reference day", "day": 20270115}],
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
        records["build_claim_pull_reading"].extend(
            {"id": f"{branch}@{tick}-{state}", "claim": branch, "observed_at": tick, "state": state,
             "source": "pull-query"}
            for tick, state in readings
        )
    return records


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/build-claim-release.md sections 1 and 2. Declare the claim kinds in a new "
        "build/schema/claims.yaml and derive build_claim_release_plan and build_claim_held in a new "
        "build/rules/claims.dl, using the verified cut, the policy date and std-decision. Write only in those "
        "two build files."
    ),
)
@pytest.mark.parametrize(("leases", "policy_known"), [([LEASE], True), ([LEASE, 2 * LEASE], False), ([], False)])
def test_build_claim_release_plan(tmp_path, leases, policy_known):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    records = capture(source, base, head, paths)
    records.update(claim_records(leases))
    rows = published(tmp_path, records)
    plans = {tuple(row["key"][:3]) for row in rows.get("build_claim_release_plan", [])}
    held = {tuple(row["key"][:3]) for row in rows.get("build_claim_held", [])}

    if not policy_known:
        assert plans == set(), f"A claim was released without one lease duration in force: {plans}"
        assert {claim for _, claim, reason in held if reason == "lease-policy-unknown"} == {
            "task/expired", "task/active", "task/renewed", "task/open", "task/unread", "task/contradicted",
            "task/old-reading",
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
    }, f"Each held claim must name exactly its own missing ground: {held}"
