"""The platform home's claim counts the written services, and only a role that reads every service sees it.

Expectation source: the written `service` rows in facts/, counted here without the engine. The claim's one row
rests on an aggregate, so a role that does not read the kind `service` in full gets no row at all (std-access:
an aggregate ranges only over a relation the role reads in full)."""

import hashlib
import json

import yaml

from case_support import ROOT
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of

CLAIM = "platform_service_count"


def written_services():
    ids = set()
    for path in sorted((ROOT / "facts").glob("*.yaml")):
        ids |= {row["id"] for row in (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("service", [])}
    return ids


def snapshot(bucket, manifest, role):
    entry, = [s for s in manifest["snapshots"] if s["role"] == role and s["relation"] == CLAIM]
    data = bucket.get(key_of(entry["uri"]))
    assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    return [tuple(item["key"]) for item in json.loads(data)]  # keys are canonical text


def test_home_claim_counts_the_services_for_a_full_reader(tmp_path):
    channels = yaml.safe_load((ROOT / "channels.yaml").read_text(encoding="utf-8"))
    assert CLAIM in channels["home"]["claim"]
    services = written_services()
    assert len(services) > 1

    epoch = batch.epoch(ROOT, epoch=1, knowledge_time="2026-01-01T00:00:00Z", sources=[("rules", "home-claim")])
    bucket = store.FileStore(tmp_path)
    published = publish.publish(epoch, bucket, {"checker": "complete", "platform-catalogue": "may_read",
                                                "elm": "may_read"})
    manifest = json.loads(bucket.get(f"{epoch.pack}/manifests/{published['id']}.json"))

    assert snapshot(bucket, manifest, "checker") == [(str(len(services)),)]
    assert snapshot(bucket, manifest, "platform-catalogue") == [(str(len(services)),)]
    # A tenant reads its own request and quota, not the services: it gets no count, not a smaller one.
    assert snapshot(bucket, manifest, "elm") == []
