"""Publish a neutral instance of the ordinary pinned Loop theory."""
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


def checked_loop_publication(root, records, *, retained, submitted=None):
    shutil.copytree(LOOP, root / "std-loop")
    shutil.copytree(ORDER, root / "std-order")
    instance = root / "instance"
    (instance / "schema").mkdir(parents=True)
    (instance / "schema" / "round.yaml").write_text(
        "id: https://example.org/round-coverage\n"
        "name: round_coverage\n"
        'imports: [linkml:types, "std-loop:step_safety", "std-loop:flow_sweep"]\n',
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
    epoch = batch.epoch(instance, epoch=1, knowledge_time="2027-01-15T08:00:00Z", sources=sources)
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
