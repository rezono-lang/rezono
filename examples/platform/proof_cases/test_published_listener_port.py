"""Follow one authored listener port through the checked platform publication and its policies."""

import hashlib
import json
import shutil

import pytest
import yaml

from case_support import ROOT
from rezono_publisher import batch, publish, store
from rezono_publisher.views import key_of


@pytest.fixture(scope="module")
def publications(tmp_path_factory):
    work = tmp_path_factory.mktemp("listener-publication")
    pack = work / "examples" / "platform"
    shutil.copytree(ROOT, pack)
    shutil.copytree(ROOT.parents[1] / "packs", work / "packs")
    path = pack / "facts" / "listener.yaml"
    facts = yaml.safe_load(path.read_text(encoding="utf-8"))
    listener, = [row for row in facts["listener_case_listener"] if row["id"] == "x-tcp"]
    assert (listener["destination"], listener["protocol"], listener["port"]) == ("x", "TCP", 443)
    editions = []
    for port in (443, 9443):
        listener["port"] = port
        path.write_text(yaml.safe_dump(facts, sort_keys=False), encoding="utf-8")
        epoch = batch.epoch(pack, epoch=1, knowledge_time="2026-01-01T00:00:00Z",
                            sources=[("facts", "listener-case")])
        bucket = store.FileStore(work / f"store-{port}")
        manifest = publish.publish(epoch, bucket, {"checker": "complete"})
        key = f"{epoch.pack}/manifests/{manifest['id']}.json"
        editions.append((bucket, json.loads(bucket.get(key))))
    return editions


def test_published_listener_port(publications):
    for (bucket, manifest), port in zip(publications, (443, 9443), strict=True):
        entry, = [item for item in manifest["snapshots"]
                  if item["role"] == "checker" and item["relation"] == "listener_case_decision"]
        raw = bucket.get(key_of(entry["uri"]))
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"]
        rows = {tuple(item["key"]) for item in json.loads(raw)}
        assert rows == {
            ("a", "x", "TCP", str(port), "allowed"), ("b", "x", "TCP", str(port), "service-isolation"),
            ("a", "y", "TCP", "443", "allowed"), ("b", "y", "TCP", "443", "service-isolation"),
            ("a", "z", "TCP", "443", "firewall"), ("b", "z", "TCP", "443", "firewall"),
        }


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Read decisions/platform-published-listener-policies.md. Implement the checked publication input for "
    "examples/platform/network_policy.py so each allowed listener row drives both policy directions."))
def test_render_published_listener_port(publications, monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    import network_policy

    render = getattr(network_policy, "render_published_network_policies", None)
    assert callable(render), "Missing NetworkPolicy renderer input for checked listener publications"
    for (bucket, manifest), port in zip(publications, (443, 9443), strict=True):
        bundle = list(render("blue", bucket, manifest, "checker"))
        assert len(bundle) == len({item["metadata"]["name"] for item in bundle}) == 5
        for item in bundle:
            assert (item["kind"], item["metadata"]["namespace"]) == ("NetworkPolicy", "blue")
        baseline, = [item["spec"] for item in bundle if item["spec"]["podSelector"] == {}]
        assert set(baseline["policyTypes"]) == {"Ingress", "Egress"}
        assert not baseline.get("ingress") and not baseline.get("egress")
        grants = []
        for item in bundle:
            spec = item["spec"]
            for direction, peers in (("ingress", "from"), ("egress", "to")):
                for rule in spec.get(direction, []):
                    local = spec["podSelector"]["matchLabels"]["rezono.org/service"]
                    for peer in rule[peers]:
                        remote = peer["podSelector"]["matchLabels"]["rezono.org/service"]
                        for binding in rule["ports"]:
                            grants.append((direction, local, remote, binding))
        expected = [(direction, local, remote, {"protocol": "TCP", "port": number})
                    for target, number in (("x", port), ("y", 443))
                    for direction, local, remote in (("ingress", target, "a"), ("egress", "a", target))]
        assert sorted(grants, key=lambda row: row[:3]) == sorted(expected, key=lambda row: row[:3])
