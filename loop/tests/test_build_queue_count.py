"""Count the planner queue in the rules from a receipted pull listing, not in the capture adapter.

The expectation is worked by hand from decisions/build-claim-release.md section 4 and
decisions/build-reconciliation.md (task and queue observations): the queue is the open pull requests against
the default branch that are not drafts, read from a complete listing that a receipt of the same run and cut
attests. With a limit of three, each excluded pull request would on its own lift the count of two to the limit.
"""
import pytest
import yaml
from test_build_claim_release_plan import ROOT
from test_build_selection import OBSERVED_AT, capture, published, repository
from test_build_task_order import task_observations

KINDS = {"BuildQueueListing", "BuildQueuePull"}
COUNTED = [(1, "open", "ready", "main"), (2, "open", "ready", "main")]
EXCLUDED = [(3, "open", "draft", "main"), (4, "open", "ready", "release"), (5, "closed", "ready", "main")]


def declared_kinds():
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def listing(records, pulls, receipt):
    records["build_queue_limit"] = [{"id": "planner-limit", "decision": "placement-policy", "limit": 3}]
    records["loop_sweep_receipt"].append({"id": "stale-round", "run": "current", "event_time": OBSERVED_AT - 1})
    records["build_queue_listing"] = [{
        "id": "listing", "run": "current", "observed_at": OBSERVED_AT, "base": "main", "source": "pull-listing",
        **({"receipt": receipt} if receipt else {}),
    }]
    records["build_queue_pull"] = [
        {"id": f"listing-{number}", "listing": "listing", "number": number, "state": state, "draft": draft,
         "base": base}
        for number, state, draft, base in pulls
    ]


@pytest.mark.parametrize(("pulls", "receipt", "known", "waiting"), [
    (COUNTED + EXCLUDED, "receipt", "2", None),
    (COUNTED + EXCLUDED + [(6, "open", "ready", "main")], "receipt", "3", "queue-limit"),
    ([], "receipt", "0", None),
    (COUNTED + EXCLUDED, None, None, "queue-evidence-unknown"),
    (COUNTED + EXCLUDED, "stale-round", None, "queue-evidence-unknown"),
], ids=["two-of-five", "at-limit", "empty", "no-receipt", "stale-receipt"])
def test_build_queue_count(tmp_path, pulls, receipt, known, waiting):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/task-policy.md")
    records = capture(source, base, head, paths)
    task_observations(records, [])
    listing(records, pulls, receipt)
    rows = published(tmp_path, records)

    assert [row["key"] for row in rows.get("build_queue_known", [])] == (
        [["current", known, "listing"]] if known is not None else []
    )
    assert [row["key"] for row in rows.get("build_planner_slot", [])] == (
        [["current", "listing", "placement-policy"]] if waiting is None else []
    )
    assert [row["key"] for row in rows.get("build_planner_waiting", [])] == (
        [["current", waiting]] if waiting is not None else []
    )
