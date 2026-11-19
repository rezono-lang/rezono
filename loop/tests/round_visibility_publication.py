"""Publish a neutral instance of the ordinary pinned Loop theory.

The retained objects are the protected caller's own inputs and the submitted objects are candidates.
Both go to the same archive. The protected caller writes its trusted context to
`observations/retained/context.json` and the index of submitted candidates to
`observations/submitted/index.json`, and hands both to `batch.epoch` as one `Evidence` with the resolver
of the archive, as decisions/admission-transport.md sections 2 to 4 fix. Admission runs before the rules
and again when the epoch is checked. A test never derives trust by listing the archive.
"""
import json
import shutil

import yaml

from pack_records import LOOP, ORDER
from rezono_canon import canonical_bytes, sha256_hex
from rezono_compiler import modules
from rezono_publisher import batch, publish, store


def observation_reference(group, name, body):
    file = f"observations/{group}/{name}.json"
    return {"file": file, "uri": f"s3://rezono/{file}", "sha256": sha256_hex(body)}


def round_context(retained, *, run, cut, manifest, invariants, program, observations, base, domain):
    """The trusted context of one round, as the protected caller pins it (admission-transport section 3).

    `cut` is the trusted cut binding. `program`, `base` and `domain` name retained objects, and
    `observations` maps each observation input of the certificate context to the retained object that holds
    it. The domain lists the steps with their integer priorities and the plan hashes of their effects in order,
    and the batch width.
    """
    def pinned(name):
        return observation_reference("retained", name, retained[name])

    return {
        "run": run, "cut": cut, "manifest": manifest, "definition_sha256": sha256_hex(retained[program]),
        "program": pinned(program), "invariants": list(invariants),
        "observations": {key: pinned(name) for key, name in sorted(observations.items())},
        "base": pinned(base), "domain": pinned(domain),
    }


def round_claim(submitted, *, run, cut, batch, members, subsets):
    """A submitted round claim: the chosen batch and, per visible subset, its variant and its certificate.

    `subsets` holds `(members, variant, certificate)` with the names of submitted objects. The claim selects
    bytes to check and confers no authority; the round verifier decides what it proves.
    """
    def pinned(name):
        return observation_reference("submitted", name, submitted[name])

    return {
        "run": run, "cut": cut, "batch": batch, "members": list(members),
        "subsets": [{"members": list(subset), "variant": pinned(variant), "certificate": pinned(certificate)}
                    for subset, variant, certificate in subsets],
    }


def pinned_evidence(archive, context, index):
    """Write context.json and index.json once and hand them to the batch boundary as one Evidence."""
    from rezono_checker.evidence import Evidence

    def put(group, name, fields, value):
        body = canonical_bytes({field: [] for field in fields} | value)
        reference = observation_reference(group, name, body)
        archive.put_new(reference["file"], body)
        return reference

    trusted = put("retained", "context", ("completeness", "rounds"), context)
    candidates = None if index is None else put("submitted", "index", ("completeness_receipts", "rounds"), index)
    return Evidence(trusted, candidates, lambda uri: archive.get(uri.removeprefix(archive.uri(""))))


def checked_loop_publication(root, records, *, retained, submitted=None, context=None, index=None):
    """Publish `records` with the retained and submitted objects. `context` and `index` are the bodies of
    context.json and index.json; without a context the batch receives no evidence."""
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
    handoff = {} if context is None else {"evidence": pinned_evidence(archive, context, index)}
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
