"""Pull request landing gate (`may_land`) and claimed merge-queue effects in the build pack."""
import hashlib
import json
from pathlib import Path
import shutil

import pytest
import yaml

from rezono_canon import canonical_json
from rezono_publisher import batch, publish, store
from test_build_selection import OBSERVED_AT, capture, repository

ROOT = Path(__file__).resolve().parents[2]
HEAD_A = "a" * 40
HEAD_B = "b" * 40
STALE_SHA = "c" * 40
GEN_A = "1" * 40
GEN_B = "2" * 40
BUILD_KINDS = {
    "BuildPullRequest",
    "BuildPrTouchedPath",
    "BuildLandingPolicy",
    "BuildCoordinatorClaim",
    "BuildMergeQueueRequest",
}
REVIEW_KINDS = {"CommitReading", "ReviewFinding"}


class MissingLandingGate(AssertionError):
    """The build landing gate schema/rules or std-review commit-reading kinds are not implemented yet."""


def _declared_classes(schema_dir: Path) -> set[str]:
    return {
        name
        for path in sorted(schema_dir.glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def _publish_build(tmp_path: Path, records: dict) -> tuple[dict[str, list[list[str]]], set[tuple[str, str]]]:
    missing_build = sorted(BUILD_KINDS - _declared_classes(ROOT / "build" / "schema"))
    missing_review = sorted(REVIEW_KINDS - _declared_classes(ROOT / "packs" / "std-review" / "schema"))
    if missing_build or missing_review:
        raise MissingLandingGate(
            f"Missing landing-gate kinds: build={missing_build}, std-review={missing_review}"
        )
    build = tmp_path / "build"
    shutil.copytree(ROOT / "build", build)
    for pack in ("std-loop", "std-order", "std-decision", "std-access", "std-review"):
        shutil.copytree(ROOT / "packs" / pack, tmp_path / "packs" / pack)
    (build / "facts").mkdir(exist_ok=True)
    (build / "facts" / "input.yaml").write_text(yaml.safe_dump(records), encoding="utf-8")
    archive = store.FileStore(tmp_path / "archive")
    epoch = batch.epoch(build, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=[("facts", "input")])
    manifest = publish.publish(epoch, archive, {"reader": "complete"})

    def read(entry: dict):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        return json.loads(data)

    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])
    rows = {
        entry["relation"]: [row["key"] for row in read(entry)]
        for entry in manifest["snapshots"]
        if entry["role"] == "reader"
    }
    witnesses = set()
    for entry in manifest["witnesses"]:
        if entry["role"] == "reader":
            for witness in read(entry)["witnesses"]:
                witnesses.add((witness["conclusion"]["relation"], witness["conclusion"]["key"]))
    return rows, witnesses


def _base_records(tmp_path: Path) -> dict:
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/landing-gate.md")
    records = capture(source, base, head, paths)
    records.update({
        "reference_date": [
            {"id": "policy-day", "title": "Observed policy cut day", "date": "2027-01-15", "day": 20270115},
        ],
        "build_policy_date": [
            {"id": "policy-cut", "run": "current", "reference": "policy-day", "observed_at": OBSERVED_AT},
        ],
        "decision": [
            {
                "id": "checker-and-access-review",
                "title": "Require independent pre-landing reading for checker and access paths",
                "state": "in_force",
                "valid_from": "2027-01-01",
                "valid_from_day": 20270101,
                "decider": ["owner"],
            },
        ],
        "build_landing_policy": [
            {
                "id": "policy-checker",
                "decision": "checker-and-access-review",
                "path_prefix": "checker/rezono_checker/",
                "upper_bound": "checker/rezono_checker0",
                "reading_policy": "require",
            },
        ],
    })
    return records


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/build-reconciliation.md: import std-review into build/pack.yaml, add CommitReading and "
        "ReviewFinding to packs/std-review, add build/schema/landing_gate.yaml and build/rules/landing_gate.dl so "
        "may_land evaluates to unknown when a required independent reading for head_sha is missing and to known with "
        "a checker-verified witness once an independent clean reading for that exact head_sha is recorded."
    ),
)
def test_may_land_is_unknown_when_required_reading_for_head_sha_is_missing(tmp_path: Path) -> None:
    records = _base_records(tmp_path / "missing")
    records.update({
        "change": [
            {
                "id": "chg-101",
                "author": "worker-1",
                "content_sha256": HEAD_A,
                "support_sha256": "0" * 64,
            },
        ],
        "build_pull_request": [
            {
                "id": "pr-101",
                "run": "current",
                "change": "chg-101",
                "head_sha": HEAD_A,
                "checks_state": "green",
                "source": "github-pr-101",
            },
        ],
        "build_pr_touched_path": [
            {
                "id": "pr-101-path-1",
                "pull_request": "pr-101",
                "path": "checker/rezono_checker/check.py",
                "is_test": "no",
                "source": "github-diff-101",
            },
        ],
        # Neither a stale commit reading nor a self-reading by the author may satisfy head_sha.
        "commit_reading": [
            {
                "id": "read-stale",
                "change": "chg-101",
                "commit_sha": STALE_SHA,
                "reviewer": "reviewer-independent",
                "outcome": "clean",
                "source": "review-log#1",
            },
            {
                "id": "read-self",
                "change": "chg-101",
                "commit_sha": HEAD_A,
                "reviewer": "worker-1",
                "outcome": "clean",
                "source": "review-log#2",
            },
        ],
    })

    rows, witnesses = _publish_build(tmp_path / "run-missing", records)
    expected_unknown = ["current", "pr-101", HEAD_A, "unknown", "missing-independent-reading"]
    assert rows.get("may_land") == [expected_unknown]
    assert ("may_land", canonical_json(expected_unknown)) in witnesses

    # Recording an independent clean reading for that exact head_sha turns may_land to known with a witness.
    records["commit_reading"].append({
        "id": "read-exact",
        "change": "chg-101",
        "commit_sha": HEAD_A,
        "reviewer": "reviewer-independent",
        "outcome": "clean",
        "source": "review-log#3",
    })
    rows_after, witnesses_after = _publish_build(tmp_path / "run-present", records)
    expected_known = ["current", "pr-101", HEAD_A, "known", "independent-reading-verified"]
    assert rows_after.get("may_land") == [expected_known]
    assert ("may_land", canonical_json(expected_known)) in witnesses_after


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/build-reconciliation.md: derive may_land as invalid with a checker-verified witness "
        "whenever an open correctness ReviewFinding exists for (change, head_sha) or when review findings or "
        "readings contradict for (change, head_sha), without silently evaluating to known or unknown."
    ),
)
def test_may_land_is_invalid_when_open_finding_exists_or_findings_contradict(tmp_path: Path) -> None:
    records = _base_records(tmp_path / "findings")
    records.update({
        "change": [
            {"id": "chg-open", "author": "worker-1", "content_sha256": HEAD_A, "support_sha256": "0" * 64},
            {"id": "chg-conflict", "author": "worker-2", "content_sha256": HEAD_B, "support_sha256": "0" * 64},
        ],
        "build_pull_request": [
            {
                "id": "pr-open",
                "run": "current",
                "change": "chg-open",
                "head_sha": HEAD_A,
                "checks_state": "green",
                "source": "github-pr-open",
            },
            {
                "id": "pr-conflict",
                "run": "current",
                "change": "chg-conflict",
                "head_sha": HEAD_B,
                "checks_state": "green",
                "source": "github-pr-conflict",
            },
        ],
        "build_pr_touched_path": [
            {
                "id": "path-open",
                "pull_request": "pr-open",
                "path": "checker/rezono_checker/check.py",
                "is_test": "no",
                "source": "github-diff-open",
            },
            {
                "id": "path-conflict",
                "pull_request": "pr-conflict",
                "path": "checker/rezono_checker/sources.py",
                "is_test": "no",
                "source": "github-diff-conflict",
            },
        ],
        "commit_reading": [
            {
                "id": "read-conflict-clean",
                "change": "chg-conflict",
                "commit_sha": HEAD_B,
                "reviewer": "reviewer-a",
                "outcome": "clean",
                "source": "review-log#10",
            },
        ],
        "review_finding": [
            {
                "id": "finding-open-1",
                "change": "chg-open",
                "commit_sha": HEAD_A,
                "reporter": "reviewer-a",
                "subject": "witness-soundness",
                "kind": "correctness",
                "status": "open",
                "source": "review-log#11",
            },
            {
                "id": "finding-conflict-open",
                "change": "chg-conflict",
                "commit_sha": HEAD_B,
                "reporter": "reviewer-b",
                "subject": "source-check",
                "kind": "correctness",
                "status": "open",
                "source": "review-log#12",
            },
            {
                "id": "finding-conflict-resolved",
                "change": "chg-conflict",
                "commit_sha": HEAD_B,
                "reporter": "reviewer-a",
                "subject": "source-check",
                "kind": "correctness",
                "status": "resolved",
                "source": "review-log#13",
            },
        ],
    })

    rows, witnesses = _publish_build(tmp_path / "run-findings", records)
    expected_open = ["current", "pr-open", HEAD_A, "invalid", "open-correctness-finding"]
    expected_conflict = ["current", "pr-conflict", HEAD_B, "invalid", "contradictory-findings"]
    may_land_rows = rows.get("may_land", [])
    assert expected_open in may_land_rows
    assert expected_conflict in may_land_rows
    assert all(row[3] == "invalid" for row in may_land_rows if row[1] in {"pr-open", "pr-conflict"})
    assert ("may_land", canonical_json(expected_open)) in witnesses
    assert ("may_land", canonical_json(expected_conflict)) in witnesses


@pytest.mark.xfail(
    strict=True,
    reason=(
        "extra: decisions/build-reconciliation.md: model merge-queue enqueue and dequeue as std-loop effects "
        "requiring a unique durable BuildCoordinatorClaim per PR and post-effect verification via receipted "
        "LoopEffectReadback, so a second coordinator without a claim receives no enqueue or dequeue effect."
    ),
)
def test_second_coordinator_without_claim_receives_no_merge_queue_effect(tmp_path: Path) -> None:
    records = _base_records(tmp_path / "effects")
    records.update({
        "loop_active_run": [{"id": "current"}],
        "loop_step": [
            {"id": "step-enq-a"},
            {"id": "step-enq-b"},
            {"id": "step-deq-a"},
            {"id": "step-deq-b"},
        ],
        "loop_effect_plan": [
            {"id": "plan-enq-a", "run": "current", "step": "step-enq-a", "reason": "merge-queue-enqueue"},
            {"id": "plan-enq-b", "run": "current", "step": "step-enq-b", "reason": "merge-queue-enqueue"},
            {"id": "plan-deq-a", "run": "current", "step": "step-deq-a", "reason": "merge-queue-dequeue"},
            {"id": "plan-deq-b", "run": "current", "step": "step-deq-b", "reason": "merge-queue-dequeue"},
        ],
        "change": [
            {"id": "chg-enq", "author": "worker-1", "content_sha256": HEAD_A, "support_sha256": "0" * 64},
            {"id": "chg-deq", "author": "worker-2", "content_sha256": HEAD_B, "support_sha256": "0" * 64},
        ],
        "build_pull_request": [
            {
                "id": "pr-enq",
                "run": "current",
                "change": "chg-enq",
                "head_sha": HEAD_A,
                "checks_state": "green",
                "source": "github-pr-enq",
            },
            {
                "id": "pr-deq",
                "run": "current",
                "change": "chg-deq",
                "head_sha": HEAD_B,
                "checks_state": "green",
                "source": "github-pr-deq",
            },
        ],
        "build_pr_touched_path": [
            {
                "id": "path-enq",
                "pull_request": "pr-enq",
                "path": "docs/vision.md",
                "is_test": "no",
                "source": "github-diff-enq",
            },
            {
                "id": "path-deq",
                "pull_request": "pr-deq",
                "path": "checker/rezono_checker/check.py",
                "is_test": "no",
                "source": "github-diff-deq",
            },
        ],
        "review_finding": [
            {
                "id": "finding-deq",
                "change": "chg-deq",
                "commit_sha": HEAD_B,
                "reporter": "reviewer-a",
                "subject": "soundness",
                "kind": "correctness",
                "status": "open",
                "source": "review-log#20",
            },
        ],
        # Only coordinator-a holds durable claims for pr-enq and pr-deq; coordinator-b holds none.
        "build_coordinator_claim": [
            {
                "id": "claim-enq-a",
                "run": "current",
                "pull_request": "pr-enq",
                "coordinator": "coordinator-a",
                "generation": GEN_A,
                "observed_at": OBSERVED_AT,
                "source": "claim-ref-enq",
            },
            {
                "id": "claim-deq-a",
                "run": "current",
                "pull_request": "pr-deq",
                "coordinator": "coordinator-a",
                "generation": GEN_B,
                "observed_at": OBSERVED_AT,
                "source": "claim-ref-deq",
            },
        ],
        "build_merge_queue_request": [
            {
                "id": "req-enq-a",
                "run": "current",
                "pull_request": "pr-enq",
                "coordinator": "coordinator-a",
                "action": "enqueue",
                "plan": "plan-enq-a",
                "step": "step-enq-a",
            },
            {
                "id": "req-enq-b",
                "run": "current",
                "pull_request": "pr-enq",
                "coordinator": "coordinator-b",
                "action": "enqueue",
                "plan": "plan-enq-b",
                "step": "step-enq-b",
            },
            {
                "id": "req-deq-a",
                "run": "current",
                "pull_request": "pr-deq",
                "coordinator": "coordinator-a",
                "action": "dequeue",
                "plan": "plan-deq-a",
                "step": "step-deq-a",
            },
            {
                "id": "req-deq-b",
                "run": "current",
                "pull_request": "pr-deq",
                "coordinator": "coordinator-b",
                "action": "dequeue",
                "plan": "plan-deq-b",
                "step": "step-deq-b",
            },
        ],
    })

    rows, witnesses = _publish_build(tmp_path / "run-planned", records)
    planned = {tuple(row) for row in rows.get("effect_planned", [])}
    assert planned == {
        ("current", "step-enq-a", "plan-enq-a", "merge-queue-enqueue"),
        ("current", "step-deq-a", "plan-deq-a", "merge-queue-dequeue"),
    }
    mq_plans = {tuple(row) for row in rows.get("build_merge_queue_effect_plan", [])}
    assert mq_plans == {
        ("current", "pr-enq", "coordinator-a", "enqueue", "plan-enq-a"),
        ("current", "pr-deq", "coordinator-a", "dequeue", "plan-deq-a"),
    }
    assert all(row[2] != "coordinator-b" for row in mq_plans)
    assert all(row[2] not in {"plan-enq-b", "plan-deq-b"} for row in planned)
    for row in planned:
        assert ("effect_planned", canonical_json(list(row))) in witnesses

    # Post-effect verification: a sent attempt plus a later receipted expected readback settles plan-enq-a as applied.
    readback_tick = OBSERVED_AT + 10
    records["loop_sweep_receipt"].append({"id": "receipt-after", "run": "current", "event_time": readback_tick})
    records["loop_effect_attempt"] = [
        {
            "id": "att-enq-a",
            "run": "current",
            "plan": "plan-enq-a",
            "sent_at": OBSERVED_AT + 5,
            "outcome": "sent",
            "source": "merge-queue-adapter",
        },
    ]
    records["loop_effect_readback"] = [
        {
            "id": "rb-enq-a",
            "run": "current",
            "plan": "plan-enq-a",
            "observed_at": readback_tick,
            "state": "expected",
            "receipt": "receipt-after",
            "source": "merge-queue-query",
        },
    ]
    rows_verified, _ = _publish_build(tmp_path / "run-verified", records)
    assert ["current", "plan-enq-a", "expected-after-attempt"] in rows_verified.get("effect_confirmed", [])
    assert ["current", "plan-enq-a", "applied", "expected-after-attempt"] in rows_verified.get("effect_state", [])
    assert all(row[2] != "plan-enq-a" for row in rows_verified.get("effect_planned", []))
