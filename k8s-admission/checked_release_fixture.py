"""Publish independent synthetic evidence through the same checker as a normal epoch."""

import json
from hashlib import sha256

from rezono_canon import canonical_json
from rezono_publisher import publish, store


MANIFEST_KEY = "admission-fixture/manifests/m-1.json"
IMAGE = "registry.example.org/sample/app@sha256:" + "a" * 64


def publish_evidence(directory, protocol="TCP", *, ports=(53,)):
    bucket = store.FileStore(directory)
    # The observed endpoints have independent namespace identities. The checker verifies
    # every same-zone conclusion and its source record before the manifest is stored.
    observed = [("admission-blue", "reader", "admission-blue", "web", "TCP", "443")]
    observed.extend(("blue", "idp", "blue", "dns", protocol, str(port)) for port in ports)
    observed.append(("blue", "idp", "other", "dns", "TCP", "443"))
    terms = ["?ns", "?source", "?destination", "?protocol", "?port"]
    premise = ["?ns", "?source", "?ns", "?destination", "?protocol", "?port"]
    rule = {"id": "same-zone", "stratum": 0,
            "head": {"relation": "admission_flow", "terms": terms},
            "body": [{"relation": "observed_flow", "terms": premise, "polarity": "positive", "stratum": 0}]}
    flows, witnesses = [], []
    for origin, source, target, destination, transport, port in observed:
        if origin != target:
            continue
        row = [origin, source, destination, transport, port]
        flows.append(row)
        witnesses.append({
            "rule_id": "same-zone", "conclusion": {"relation": "admission_flow", "key": canonical_json(row)},
            "bindings": [{"variable": var, "value": value} for var, value in zip(terms, row)],
            "premises": [{"row": {"relation": "observed_flow",
                                  "key": canonical_json([origin, source, target, destination, transport, port])},
                          "polarity": "positive", "stratum": 0}],
        })
    rows = {"observed_flow": observed, "admission_flow": flows,
            "image_build": [("admission-blue", "web", IMAGE), ("admission-blue", "unsigned", IMAGE)],
            "image_signature": [("admission-blue", "web", IMAGE), ("other", "unsigned", IMAGE)]}
    columns = {"observed_flow": [None] * 6, "image_build": [None] * 3, "image_signature": [None] * 3}
    rules = {"format": "rezono.rules/1", "relations": [{"name": "admission_flow", "role": "derived"}],
             "rules": [rule]}
    epoch = publish.Epoch(
        pack="admission-fixture", epoch=1, knowledge_time="2026-01-01T00:00:00Z",
        pack_sha256=sha256(canonical_json(rows).encode()).hexdigest(), definition_sha256="1" * 64,
        compiler_sha256="2" * 64, schema_version="0.1.0", engine={"name": "fixture", "version": "1"},
        sources=[("fixture", "1")], checks=[], kinds=frozenset(), columns=columns,
        rows=rows, rules=json.dumps(rules), witnesses=witnesses,
    )
    publish.publish(epoch, bucket, {"checker": "complete"})
    return bucket
