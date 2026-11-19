"""Read the loop's undecided cut and its grounds from a checked publication."""
import hashlib
import json
import shutil

import pytest
import yaml

from pack_records import LOOP, ORDER
from rezono_compiler import modules
from rezono_publisher import batch, publish, store


def _publish(root, *, second_at):
    shutil.copytree(LOOP, root / "std-loop")
    shutil.copytree(ORDER, root / "std-order")
    app = root / "round"
    (app / "schema").mkdir(parents=True)
    (app / "schema" / "reader.yaml").write_text(
        "id: https://example.org/round-reader\n"
        "name: round_reader\n"
        'imports: [linkml:types, "std-loop:step_safety"]\n',
        encoding="utf-8",
    )
    (app / "pack.yaml").write_text(yaml.safe_dump({
        "name": "round-reader", "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-loop", "path": "../std-loop",
                     "sha256": modules.pack_hash(root / "std-loop")}],
    }), encoding="utf-8")
    (app / "channels.yaml").write_text("kinds: []\n", encoding="utf-8")
    (app / "labels").mkdir()
    (app / "labels" / "en.yaml").write_text("waiting: Waiting step\n", encoding="utf-8")
    (app / "facts").mkdir()
    (app / "facts" / "observation.yaml").write_text(yaml.safe_dump({
        "loop_active_run": [{"id": "run"}],
        "loop_step": [{"id": "transfer"}, {"id": "unrelated"}],
        "loop_sweep_receipt": [
            {"id": "left-cut", "run": "run", "event_time": 10},
            {"id": "right-cut", "run": "run", "event_time": second_at},
            {"id": "foreign-cut", "run": "prior", "event_time": 11},
        ],
        "loop_step_safety_check": [
            {"id": "left-check", "run": "run", "step": "transfer", "cut": "left-cut",
             "obligation": "target-readable", "verdict": "proved", "reason": "target-confirmed"},
            {"id": "right-check", "run": "run", "step": "transfer", "cut": "right-cut",
             "obligation": "target-readable", "verdict": "refuted", "reason": "target-missing"},
        ],
    }), encoding="utf-8")
    epoch = batch.epoch(app, epoch=1, knowledge_time="2027-01-15T08:00:00Z",
                        sources=[("observations", "round-one")])
    archive = store.FileStore(root / "archive")
    published = publish.publish(epoch, archive, {"reader": "complete"})
    manifest = json.loads(archive.get(f"round-reader/manifests/{published['id']}.json"))
    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])

    def read(entry):
        data = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
        return json.loads(data)

    snapshots = {
        entry["relation"]: [row["key"] for row in read(entry)]
        for entry in manifest["snapshots"]
        if entry["role"] == "reader" and entry["relation"] in {"waiting", "safe_alone"}
    }
    witness_entry, = [entry for entry in manifest["witnesses"] if entry["role"] == "reader"]
    return snapshots, read(witness_entry)["witnesses"]


def _receipt_grounds(witnesses, row):
    def reference(item):
        return item["relation"], tuple(json.loads(item["key"]))

    by_head = {reference(witness["conclusion"]): witness for witness in witnesses}
    pending = [("waiting", tuple(row))]
    seen, receipts = set(), set()
    while pending:
        relation, key = pending.pop()
        if (relation, key) in seen:
            continue
        seen.add((relation, key))
        if relation in {"loop_sweep_receipt", "loop_sweep_receipt__run", "loop_sweep_receipt__event_time"}:
            receipts.add(key[0])
        witness = by_head.get((relation, key))
        if witness is not None:
            pending.extend(reference(premise["row"]) for premise in witness["premises"]
                           if premise["polarity"] == "positive")
    return receipts


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason=(
        "Read decisions/safe-step-rounds.md sections 1 to 3. Expose a waiting reason when the latest same-run "
        "safety cut is ambiguous, with both receipt identities as grounds in the ordinary publication. "
        "Keep unrelated steps and earlier or foreign cuts out of this result. Write in packs/std-loop "
        "and refresh its dependent Build pin."
    ),
)
def test_waiting_publication_explains_ambiguous_safety_cut(tmp_path):
    # A supplied "proved" verdict is a claim, not authority (decisions/loop-certificate-admission.md), so the
    # unique case only shows that the superseded refutation at the earlier cut leaves nothing waiting.
    snapshots, _ = _publish(tmp_path / "unique", second_at=9)
    assert snapshots["waiting"] == []

    snapshots, witnesses = _publish(tmp_path / "ambiguous", second_at=10)
    assert snapshots["safe_alone"] == []
    waiting = snapshots["waiting"]
    assert len(waiting) == 1 and waiting[0][:2] == ["run", "transfer"], (
        "The reader needs a waiting reason for the transfer when both receipts claim its latest cut"
    )
    assert all(waiting[0][2:]), "The waiting row needs an obligation and reason"
    assert _receipt_grounds(witnesses, waiting[0]) == {"left-cut", "right-cut"}
