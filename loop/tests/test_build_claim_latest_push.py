"""Take the lease start from the latest push of a claim, never from an older matching push.

The capture adapter passes every push record of a claim, each with its own source and exact time. The rules
choose. The expectation is worked by hand from decisions/build-claim-release.md sections 1 and 2: the latest
push supplies the lease start only when its resulting commit equals the observed generation, and the lease
has ended when that start plus the duration is at most the cut tick.
"""
import pytest
from test_build_claim_release_plan import CLAIM_RECEIPTS, KINDS, LEASE, claim_records, declared_kinds, generation
from test_build_selection import OBSERVED_AT, capture, published, repository


def latest_push_records():
    t = OBSERVED_AT
    cases = {
        # branch: [(pushed generation name, pushed_at), ...] in no particular order
        # A renewal: the older push made another commit, the newer one the observed generation, long enough ago.
        "task/renewed-ended": [("task/renewed-ended-before", t - 10 * LEASE), ("task/renewed-ended", t - LEASE)],
        # The observed generation was pushed once long ago and again within the lease: the latest push counts.
        "task/repushed": [("task/repushed", t - 10 * LEASE), ("task/repushed", t - LEASE + 1)],
        # The latest push made another commit than the one listed: an older matching push starts no lease.
        "task/raced": [("task/raced", t - 10 * LEASE), ("task/raced-after", t - 1)],
        # Two equally recent pushes with different commits leave the latest push undecided, even though one of
        # them made the observed generation long enough ago.
        "task/tied": [("task/tied", t - LEASE), ("task/tied-other", t - LEASE)],
    }
    records = claim_records([LEASE])
    records.update(build_claim=[], build_claim_activity=[], build_claim_pull_reading=[])
    for branch, pushes in cases.items():
        records["build_claim"].append({"id": branch, "run": "current", "branch": branch,
                                       "generation": generation(branch), "observed_at": t,
                                       "source": "ref-listing"})
        for pushed, pushed_at in pushes:
            after = generation(pushed)
            records["build_claim_activity"].append({"id": f"{branch}@{after}@{pushed_at}", "claim": branch,
                                                    "after": after, "pushed_at": pushed_at,
                                                    "source": "push-activity"})
        records["build_claim_pull_reading"].append({"id": f"{branch}@{t}-none", "claim": branch,
                                                    "observed_at": t, "state": "none", "source": "pull-query",
                                                    "receipt": "receipt"})
    return records


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/build-claim-release.md sections 1 and 2. build_claim_activity holds every push record of "
        "a claim. Take the latest push per claim by pushed_at; two equally recent pushes with different commits "
        "leave it undecided. The latest push supplies the lease start only when its after "
        "equals the observed generation. An older matching push never starts a lease. Write in "
        "build/rules/claims.dl. Waits for test_build_claim_release_plan (same file, adds the claim kinds). Today "
        "the build schema lacks the claim kinds."
    ),
)
def test_build_claim_latest_push(tmp_path):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/claims.md")
    records = capture(source, base, head, paths)
    records.update(latest_push_records())
    records["loop_sweep_receipt"].extend(CLAIM_RECEIPTS)
    rows = published(tmp_path, records)
    plans = {tuple(row["key"][:3]) for row in rows.get("build_claim_release_plan", [])}
    held = {tuple(row["key"][:3]) for row in rows.get("build_claim_held", [])}

    assert plans == {("current", "task/renewed-ended", generation("task/renewed-ended"))}, (
        f"Only the claim whose latest push made the observed generation at least one lease ago is planned: {plans}"
    )
    assert held == {
        ("current", "task/repushed", "lease-active"),
        ("current", "task/raced", "lease-unknown"),
        ("current", "task/tied", "lease-unknown"),
    }, f"An older push must not start the lease: {held}"
