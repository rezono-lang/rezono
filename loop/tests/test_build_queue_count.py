"""Count the planner queue in the rules from the admitted inventory of a pull listing, not from its records.

The expectations are worked by hand from decisions/build-claim-release.md section 4,
decisions/build-reconciliation.md (task and queue observations) and decisions/admission-transport.md section 6
(queue pulls): the queue is the open pull requests against the default branch that are not drafts. Each is a
member ["queue-pull", base, number] of the admitted receipt that the listing names, beside the member
["queue-listing", base] of the read itself. With a limit of three, each excluded pull request would on its own lift
the count of two to the limit.

Most cases read the rows of the rules from the same epoch that a publication makes, without its witness instances
(`derived`): computing every witness instance takes most of a publication's time. The proofs of the count, a slot
and a waiting reason are published and checked once, in test_build_queue_count_is_published.
"""
import shutil
from unittest import mock

import pytest
import yaml
from rezono_compiler import batch as engine
from rezono_publisher import batch, publish, store
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


class MissingQueueListingMember(AssertionError):
    """The planner queue is counted from a receipt without its single tagged listing member for the base."""


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


RELATIONS = ("build_queue_known", "build_planner_slot", "build_planner_waiting")


def derived(tmp, records, evidence=None):
    """The rows of `records` through the build pack in the epoch `published` makes, before it is published.

    The epoch is the same, with the same facts, admitted evidence and checks, except that it computes no witness
    instances; a publication blocks on a red check, so every check must be green here too. Rows come back as the
    reader's snapshot gives them: {"key": [text, ...]}, sorted by key."""
    build = tmp / "build"
    shutil.copytree(ROOT / "build", build)
    for pack in ("std-loop", "std-order", "std-decision"):
        shutil.copytree(ROOT / "packs" / pack, tmp / "packs" / pack)
    (build / "facts").mkdir()
    (build / "facts" / "input.yaml").write_text(yaml.safe_dump(records), encoding="utf-8")
    handoff = {} if evidence is None else {"evidence": evidence(store.FileStore(tmp / "archive"))}
    with mock.patch.object(engine, "witnesses", lambda con, prog, rule_ids=None: {}):
        epoch = batch.epoch(build, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=[("facts", "input")],
                            **handoff)
    assert not epoch.witnesses
    red = [check for check in epoch.checks if check["status"] == "red"]
    assert not red, f"red checks would block the publication: {red}"
    assert all(check["status"] == "green" for check in epoch.checks if check["name"] != "rezono:origins")
    return {relation: [{"key": list(row)} for row in sorted(set(rows), key=publish.key_text)]
            for relation, rows in epoch.rows.items()}


def outcome(tmp_path, records, evidence, publication=derived):
    rows = publication(tmp_path, records, evidence)
    return tuple([row["key"] for row in rows.get(relation, [])] for relation in RELATIONS)


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


# One count with a planner slot, and one at the limit with a waiting reason: the checker checks the proof of each
# published row of the queue count against the reader's snapshots.
@pytest.mark.parametrize(("pulls", "inventory", "known", "waiting"), [
    pytest.param(COUNTED + EXCLUDED, [1, 2], "2", None, id="slot"),
    pytest.param(COUNTED + EXCLUDED + [SIXTH], [1, 2, 6], "3", "queue-limit", id="waiting"),
])
def test_build_queue_count_is_published(tmp_path, pulls, inventory, known, waiting):
    records = submitted(tmp_path)
    evidence = listing(records, pulls, "admitted", (queue_members(inventory),))
    assert outcome(tmp_path, records, evidence, published) == expected(known, waiting)


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
# Each case is one epoch; the cases are split over two tests so that each stays well inside the worker's check.
# The population: no admitted receipt, or one that omits a pull request or lacks a recorded one.
POPULATION_CASES = ("records-only", "omitted-pull", "unlisted-record")
# The read itself: its tag, its base, its listing member and that one admitted receipt carries it.
LISTING_CASES = ("untagged", "other-base", "no-listing-member", "second-receipt")


def counter_outcomes(tmp_path, cases):
    """The outcome of each of `cases` in COUNTER_CASES that is not its expectation, by case."""
    wrong = {}
    for case in cases:
        pulls, receipt, inventories, want = COUNTER_CASES[case]
        records = submitted(tmp_path / case)
        evidence = listing(records, pulls, receipt, inventories)
        actual = outcome(tmp_path / case, records, evidence)
        if actual != expected(*want):
            wrong[case] = actual
    return wrong


def test_planner_slot_needs_verified_pull_inventory(tmp_path):
    records = submitted(tmp_path / "admitted")
    evidence = listing(records, COUNTED + EXCLUDED, "admitted", (queue_members([1, 2]),))
    assert outcome(tmp_path / "admitted", records, evidence) == expected("2", None)

    assert set(POPULATION_CASES) | set(LISTING_CASES) == set(COUNTER_CASES)
    wrong = counter_outcomes(tmp_path, POPULATION_CASES)

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


def test_planner_count_needs_the_listing_member(tmp_path):
    wrong = counter_outcomes(tmp_path, LISTING_CASES)
    if wrong:
        raise MissingQueueListingMember(f"a planner slot or count without the listing member: {wrong}")
