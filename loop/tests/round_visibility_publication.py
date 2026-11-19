"""Publish a neutral instance of the ordinary pinned Loop theory.

The retained objects are the protected caller's context and the submitted objects are candidates.
Both go to the same archive. `admission` names the candidates and the trusted contexts for the batch
boundary, as decisions/scoped-completeness.md (admission and replay transport) and
decisions/loop-certificate-admission.md fix. The helper passes them to `batch.epoch` with the archive
that resolves them, so admission runs before the rules and again when the epoch is checked.
"""
import json
import shutil

import yaml

from pack_records import LOOP, ORDER
from rezono_canon import sha256_hex
from rezono_compiler import modules
from rezono_publisher import batch, publish, store


def observation_reference(group, name, body):
    file = f"observations/{group}/{name}.json"
    return {"file": file, "uri": f"s3://rezono/{file}", "sha256": sha256_hex(body)}


def retained_references(retained):
    """Pin every retained object by digest, as the protected caller's context refers to them."""
    return {name: observation_reference("retained", name, body) for name, body in sorted(retained.items())}


def round_authority(retained, *, run, cut):
    """The trusted context of one round: its run and cut and every retained object of that round."""
    return {"run": run, "cut": cut, "retained": retained_references(retained)}


def round_candidates(submitted):
    """Every submitted round object is a candidate. The round verifier decides what each one proves."""
    return [observation_reference("submitted", name, body) for name, body in sorted(submitted.items())]


def checked_loop_publication(root, records, *, retained, submitted=None, admission=None):
    shutil.copytree(LOOP, root / "std-loop")
    shutil.copytree(ORDER, root / "std-order")
    instance = root / "instance"
    (instance / "schema").mkdir(parents=True)
    (instance / "schema" / "round.yaml").write_text(
        "id: https://example.org/round-coverage\n"
        "name: round_coverage\n"
        'imports: [linkml:types, "std-loop:step_safety", "std-loop:flow_sweep", "std-loop:batch_selection"]\n',
        encoding="utf-8",
    )
    (instance / "pack.yaml").write_text(yaml.safe_dump({
        "name": "round-coverage", "version": "0.1.0", "default_language": "en",
        "imports": [{"name": "std-loop", "path": "../std-loop",
                     "sha256": modules.pack_hash(root / "std-loop")}],
    }), encoding="utf-8")
    (instance / "channels.yaml").write_text("kinds: []\n", encoding="utf-8")
    (instance / "labels").mkdir()
    (instance / "labels" / "en.yaml").write_text("ready: Ready step\n", encoding="utf-8")
    (instance / "facts").mkdir()
    (instance / "facts" / "capture.yaml").write_text(yaml.safe_dump(records), encoding="utf-8")
    archive = store.FileStore(root / "archive")
    for group, objects in (("retained", retained), ("submitted", submitted or {})):
        for name, body in objects.items():
            archive.put_new(observation_reference(group, name, body)["file"], body)
    sources = [(name, sha256_hex(body)) for name, body in retained.items()]
    handoff = {} if admission is None else {**admission, "archive": archive}
    epoch = batch.epoch(instance, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=sources, **handoff)
    emitted = publish.publish(epoch, archive, {"reader": "complete"})
    manifest = json.loads(archive.get(f"round-coverage/manifests/{emitted['id']}.json"))
    assert any(check["name"] == "rezono:proofs" and check["status"] == "green" for check in manifest["checks"])

    def read(entries):
        entry, = [candidate for candidate in entries if candidate["role"] == "reader"]
        body = archive.get(entry["uri"].removeprefix(archive.uri("")))
        assert sha256_hex(body) == entry["sha256"]
        return json.loads(body)

    def rows(relation):
        entries = [entry for entry in manifest["snapshots"] if entry["relation"] == relation]
        return {tuple(row["key"]) for row in read(entries)}

    return manifest, rows, read(manifest["witnesses"])["witnesses"]
