"""Count the planner queue in the rules from the admitted inventory of a pull listing, not from its records.

The expectations are worked by hand from decisions/build-claim-release.md section 4,
decisions/build-reconciliation.md (task and queue observations) and decisions/admission-transport.md section 6
(queue pulls): the queue is the open pull requests against the default branch that are not drafts. Each is a
member ["queue-pull", base, number] of the admitted receipt that the listing names, beside the member
["queue-listing", base] of the read itself. With a limit of three, each excluded pull request would on its own lift
the count of two to the limit.
"""
import pytest
import yaml
from test_build_claim_release_plan import ROOT
from test_build_selection import OBSERVED_AT, capture, published, repository
from test_build_task_order import queue_evidence, queue_listing, queue_members, task_observations

KINDS = {"BuildQueueListing", "BuildQueuePull"}
COUNTED = [(1, "open", "ready", "main"), (2, "open", "ready", "main")]
EXCLUDED = [(3, "open", "draft", "main"), (4, "open", "ready", "release"), (5, "closed", "ready", "main")]
SIXTH = (6, "open", "ready", "main")
SLOT = [["current", "listing", "placement-policy"]]


class MissingVerifiedQueue(AssertionError):
    """The planner queue is counted from submitted records instead of the admitted pull inventory."""


def declared_kinds():
    return {
        name
        for path in sorted((ROOT / "build" / "schema").glob("*.yaml"))
        for name in (yaml.safe_load(path.read_text(encoding="utf-8")).get("classes") or {})
    }


def listing(records, pulls, receipt, inventories=()):
    """Record the listing with `pulls` and return the evidence of the protected reads, or None.

    `receipt` is "admitted" to cite the receipt of the first of `inventories`, another receipt record, or None.
    """
    records["build_queue_limit"] = [{"id": "planner-limit", "decision": "placement-policy", "limit": 3}]
    records["loop_sweep_receipt"].append({"id": "stale-round", "run": "current", "event_time": OBSERVED_AT - 1})
    evidence = None
    if inventories:
        digests, evidence = queue_evidence(*inventories)
        receipt = digests[0] if receipt == "admitted" else receipt
    queue_listing(records, "listing", pulls, receipt=receipt)
    return evidence


def outcome(tmp_path, records, evidence):
    rows = published(tmp_path, records, evidence)
    return tuple([row["key"] for row in rows.get(relation, [])]
                 for relation in ("build_queue_known", "build_planner_slot", "build_planner_waiting"))


def expected(known, waiting):
    return ([["current", known, "listing"]] if known is not None else [],
            SLOT if waiting is None else [], [["current", waiting]] if waiting is not None else [])


def submitted(tmp_path):
    tmp_path.mkdir(exist_ok=True)
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/task-policy.md")
    records = capture(source, base, head, paths)
    task_observations(records)
    return records


@pytest.mark.parametrize(("pulls", "receipt", "inventory", "known", "waiting"), [
    pytest.param(COUNTED + EXCLUDED, "admitted", [1, 2], "2", None, id="two-of-five"),
    pytest.param(COUNTED + EXCLUDED + [SIXTH], "admitted", [1, 2, 6], "3", "queue-limit", id="at-limit"),
    # The submitted listing is empty while the admitted read lists three pull requests: the queue is at its limit.
    pytest.param([], "admitted", [1, 2, 6], "3", "queue-limit", id="empty"),
    pytest.param([], "admitted", [], "0", None, id="verified-empty"),
    pytest.param(COUNTED + EXCLUDED, None, None, None, "queue-evidence-unknown", id="no-receipt"),
    pytest.param(COUNTED + EXCLUDED, "stale-round", None, None, "queue-evidence-unknown", id="stale-receipt"),
])
def test_build_queue_count(tmp_path, pulls, receipt, inventory, known, waiting):
    assert KINDS <= declared_kinds(), f"The build schema lacks {sorted(KINDS - declared_kinds())}"
    records = submitted(tmp_path)
    evidence = listing(records, pulls, receipt, () if inventory is None else (queue_members(inventory),))
    actual = outcome(tmp_path, records, evidence)
    if actual != expected(known, waiting):
        raise MissingVerifiedQueue(f"known, slot and waiting: {actual}")


# Each case drops one ground of the count: the admitted receipt, the full population, the tag, the base, the read
# itself, a recorded pull request, or the listing altogether. None of them may leave a planner slot.
COUNTER_CASES = {
    "records-only": (COUNTED, "receipt", (), (None, "queue-evidence-unknown")),
    "omitted-pull": (COUNTED + EXCLUDED, "admitted", (queue_members([1, 2, 6]),), ("3", "queue-limit")),
    "untagged": (COUNTED, "admitted", ([["main"], ["main", 1], ["main", 2]],), (None, "queue-evidence-unknown")),
    "other-base": (COUNTED, "admitted", (queue_members([1, 2], base="release"),), (None, "queue-evidence-unknown")),
    "no-listing-member": (COUNTED, "admitted", (queue_members([1, 2])[1:],), (None, "queue-evidence-unknown")),
    "unlisted-record": (COUNTED, "admitted", (queue_members([1]),), (None, "queue-evidence-unknown")),
    "second-receipt": (COUNTED, "admitted", (queue_members([1, 2]), queue_members([1, 2, 6])),
                       (None, "queue-evidence-unknown")),
}


def test_planner_slot_needs_verified_pull_inventory(tmp_path):
    records = submitted(tmp_path / "admitted")
    evidence = listing(records, COUNTED + EXCLUDED, "admitted", (queue_members([1, 2]),))
    assert outcome(tmp_path / "admitted", records, evidence) == expected("2", None)

    wrong = {}
    for case, (pulls, receipt, inventories, want) in COUNTER_CASES.items():
        records = submitted(tmp_path / case)
        evidence = listing(records, pulls, receipt, inventories)
        actual = outcome(tmp_path / case, records, evidence)
        if actual != expected(*want):
            wrong[case] = actual

    # A reported count of the old reading path, with a receipt of the run's cut but no admitted listing.
    records = submitted(tmp_path / "reading")
    records["build_queue_limit"] = [{"id": "planner-limit", "decision": "placement-policy", "limit": 3}]
    records["build_queue_reading"] = [{"id": "reading", "run": "current", "observed_at": OBSERVED_AT, "count": 0,
                                       "source": "queue-reader", "receipt": "receipt"}]
    actual = outcome(tmp_path / "reading", records, None)
    if actual[1] or actual[2] != [["current", "queue-evidence-unknown"]]:
        wrong["reading-only"] = actual
    if wrong:
        raise MissingVerifiedQueue(f"a planner slot or count without the admitted pull inventory: {wrong}")
