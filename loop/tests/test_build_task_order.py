"""Publish task and planner decisions through the real loop and decision libraries."""
from pathlib import Path

import pytest
import yaml

from rezono_canon import canonical_bytes, canonical_json, canonical_sha256
from round_visibility_publication import observation_reference, pinned_evidence
from test_build_selection import OBSERVED_AT, capture, published, repository

ROOT = Path(__file__).resolve().parents[2]
QUEUE_READER = "pull-listing"
OPEN = [(number, "open", "ready", "main") for number in range(1, 31)]


def task_observations(data):
    run = "current"
    tasks = ("language", "core", "waiting", "declined")
    data.update({
        "loop_active_run": [{"id": run}],
        "loop_step": [{"id": task, **({"precedes": ["waiting"]} if task == "core" else {})} for task in tasks],
        "loop_completion": [
            {"id": "core-evidence", "run": run, "step": "core", "token": "compiled-core", "reason": "compile-result"}
        ],
        "loop_expectation": [{"id": "compiled-core", "value": "passed"}],
        "loop_refusal": [{"id": "decline", "run": run, "step": "declined", "reason": "terminal-refusal"}],
        "build_task": [
            {"id": "task-" + task, "run": run, "step": task,
             "track": "core" if task == "core" else "language", "source": "task-board"}
            for task in tasks
        ],
        "reference_date": [{"id": "policy-day", "title": "Observed reference day", "day": 20270115}],
        "build_policy_date": [
            {"id": "policy-cut", "run": run, "reference": "policy-day", "observed_at": OBSERVED_AT}
        ],
        "decision": [
            {"id": "placement-policy", "title": "Build placement", "state": "in_force",
             "valid_from": "2027-01-01", "valid_from_day": 20270101, "decider": ["build-policy"]}
        ],
        "build_track_rank": [
            {"id": "language-first", "decision": "placement-policy", "track": "language", "rank": 0},
            {"id": "core-next", "decision": "placement-policy", "track": "core", "rank": 1},
        ],
        "build_queue_limit": [{"id": "planner-limit", "decision": "placement-policy", "limit": 30}],
    })


def queue_members(numbers, base="main"):
    """The trusted member keys of one pull listing (decisions/admission-transport.md section 6, queue pulls):
    the read itself, also when it lists nothing, and each open pull request against the base that is not a draft."""
    return [["queue-listing", base], *(["queue-pull", base, number] for number in numbers)]


def _pull_number_is_text():
    """Return True once BuildQueuePull.number uses string range to match verified_member part 2."""
    schema = yaml.safe_load((ROOT / "build" / "schema" / "tasks.yaml").read_text(encoding="utf-8"))
    slot = (schema.get("classes") or {}).get("BuildQueuePull", {}).get("attributes", {}).get("number") or {}
    return slot.get("range", schema.get("default_range", "string")) == "string"


def queue_listing(data, listing, pulls, *, observed_at=OBSERVED_AT, receipt=None, base="main"):
    """Record one submitted listing of the run with its `(number, state, draft, base)` pulls. `receipt` names the
    receipt the listing cites, if any; a cited receipt without a record is recorded at the listing's cut."""
    data.setdefault("build_queue_listing", []).append({
        "id": listing, "run": "current", "observed_at": observed_at, "base": base, "source": QUEUE_READER,
        **({"receipt": receipt} if receipt else {}),
    })
    if receipt and all(row["id"] != receipt for row in data["loop_sweep_receipt"]):
        data["loop_sweep_receipt"].append({"id": receipt, "run": "current", "event_time": observed_at})
    as_text = _pull_number_is_text()
    data.setdefault("build_queue_pull", []).extend(
        {"id": f"{listing}-{number}", "listing": listing, "number": str(number) if as_text else number,
         "state": state, "draft": draft, "base": pull_base}
        for number, state, draft, pull_base in pulls
    )


def queue_evidence(*inventories):
    """The protected caller's reads of the run's pull listings, one receipt per inventory of member keys.

    Returns the receipt digests in order, and a function that stores the retained and submitted objects in an
    archive and returns the Evidence for the batch boundary (decisions/admission-transport.md sections 2 to 4).
    """
    objects, authorities, references, digests = {}, [], [], []

    def pinned(group, name, value):
        body = canonical_bytes(value)
        objects[group, name] = body
        return observation_reference(group, name, body)

    for index, inventory in enumerate(inventories):
        content = [{"key": key, "terminal": {"kind": "tool", "name": QUEUE_READER, "position": canonical_json(key)},
                    "rows": []} for key in inventory]
        context = {
            "source": {"kind": "tool", "name": QUEUE_READER, "position": str(OBSERVED_AT)},
            "issuer": {"id": QUEUE_READER, "authorization": pinned(
                "retained", f"queue-authority-{index}", {"issuer": QUEUE_READER, "query": "open-ready-pulls"})},
            "scope": {
                "definition": pinned("retained", f"queue-scope-{index}", {"query": "open-ready-pulls", "read": index}),
                "query": "open-ready-pulls",
                "bindings": [{"name": "read", "type": "string", "value": str(index)},
                             {"name": "run", "type": "string", "value": "current"}],
            },
            "cut": {"frontier": {"source_id": QUEUE_READER, "position": str(OBSERVED_AT)}},
        }
        authorities.append({**context, "inventory": pinned("retained", f"queue-inventory-{index}", inventory),
                            "content": pinned("retained", f"queue-content-{index}", content)})
        body = {**context, "inventory": pinned("submitted", f"queue-inventory-{index}", inventory),
                "content": pinned("submitted", f"queue-content-{index}", content)}
        receipt = {"id": canonical_sha256(["rezono.completeness-receipt/1", body]), **body}
        digests.append(receipt["id"])
        references.append(pinned("submitted", f"queue-receipt-{index}", receipt))

    def install(archive):
        for (group, name), body in objects.items():
            archive.put_new(observation_reference(group, name, body)["file"], body)
        return pinned_evidence(archive, {"completeness": authorities}, {"completeness_receipts": references})

    return digests, install


def planner_listings(data, listings):
    """Record each `(tick, count, admitted)` listing of `count` open pull requests as `queue-<index>` and return
    the evidence, or None. An admitted listing cites the receipt of a protected read that lists the same pulls."""
    admitted = [index for index, (_, _, read) in enumerate(listings) if read]
    digests, evidence = queue_evidence(*(queue_members(range(1, listings[index][1] + 1)) for index in admitted))
    receipts = dict(zip(admitted, digests, strict=True))
    for index, (tick, count, _) in enumerate(listings):
        queue_listing(data, f"queue-{index}", OPEN[:count], observed_at=tick, receipt=receipts.get(index))
    return evidence if admitted else None


@pytest.mark.parametrize(("listings", "waiting_reason"), [
    ([(OBSERVED_AT, 29, True)], None),
    ([(OBSERVED_AT, 30, True)], "queue-limit"),
    ([(OBSERVED_AT - 1, 29, True)], "queue-evidence-unknown"),
    ([(OBSERVED_AT, 29, True), (OBSERVED_AT, 30, True)], "queue-evidence-unknown"),
    # A listing without the receipt of its complete read does not prove planner capacity.
    ([(OBSERVED_AT, 29, False)], "queue-evidence-unknown"),
])
def test_build_task_order_and_planner_limit(tmp_path, listings, waiting_reason):
    source = tmp_path / "source"
    base, head, paths = repository(source, "decisions/task-policy.md")
    records = capture(source, base, head, paths)
    task_observations(records)
    rows = published(tmp_path, records, planner_listings(records, listings))

    assert {row["key"][1] for row in rows["build_task_ready"]} == {"task-language", "task-core"}
    assert [row["key"][:3] for row in rows["build_task_waiting"]] == [["current", "task-waiting", "compiled-core"]]
    assert {row["key"][1] for row in rows["build_task_stuck"]} == {"task-declined"}
    assert [row["key"] for row in rows["build_task_precedes"]] == [["current", "task-language", "task-core"]]
    assert [row["key"] for row in rows["build_planner_slot"]] == (
        [["current", "queue-0", "placement-policy"]] if waiting_reason is None else []
    )
    assert [row["key"] for row in rows["build_planner_waiting"]] == (
        [["current", waiting_reason]] if waiting_reason is not None else []
    )
