"""The selected publisher manifest is independent of the proposed Kubernetes resource."""

from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path

import pytest
import yaml
from rezono_publisher.views import key_of

from admission_release import render_release
from checked_release_fixture import MANIFEST_KEY, publish_evidence


@pytest.fixture
def release(tmp_path):
    store = publish_evidence(tmp_path / "reviewed")
    path = Path(__file__).parent / "fixtures" / "server" / "publication.yaml"
    return store, yaml.safe_load(path.read_bytes())


@pytest.mark.parametrize(("field", "message"), [("flows", "flow rows"), ("images", "image rows")])
def test_checked_release_refuses_changed_rows(release, field, message):
    store, publication = release
    namespace = publication["metadata"]["namespace"]
    options = {"store": store, "manifest_key": MANIFEST_KEY}
    assert publication in render_release([namespace], [publication], **options)
    changed = deepcopy(publication)
    changed["spec"][field] = []
    with pytest.raises(ValueError, match=message):
        render_release([namespace], [changed], **options)


def test_other_manifest_cannot_supply_the_digest(release, tmp_path):
    store, publication = release
    other = publish_evidence(tmp_path / "other", "UDP")
    publication["spec"]["digest"] = sha256(other.get(MANIFEST_KEY)).hexdigest()
    with pytest.raises(ValueError, match="release digest"):
        render_release(["admission-blue"], [publication], store=store, manifest_key=MANIFEST_KEY)


@pytest.mark.parametrize("protocol", ["UDP", "SCTP"])
def test_checked_transport_rows_retain_their_protocol(tmp_path, protocol):
    store = publish_evidence(tmp_path, protocol)
    row = {"source": "idp", "destination": "dns", "port": 53}
    publication = {
        "apiVersion": "admission.rezono.org/v1alpha1", "kind": "NamespacePublication",
        "metadata": {"name": "transport", "namespace": "blue"},
        "spec": {"digest": sha256(store.get(MANIFEST_KEY)).hexdigest(), "images": [], "flows": [],
                 "transportFlows": [dict(row, protocol=protocol)]},
    }
    options = {"store": store, "manifest_key": MANIFEST_KEY}
    assert publication in render_release(["blue"], [publication], **options)
    publication["spec"].update(flows=[row], transportFlows=[])
    with pytest.raises(ValueError, match="flow rows"):
        render_release(["blue"], [publication], **options)


def test_release_verifies_the_referenced_snapshot_bytes(release):
    store, publication = release
    manifest = json.loads(store.get(MANIFEST_KEY))
    entry, = (s for s in manifest["snapshots"] if s["relation"] == "admission_flow")
    (store.root / key_of(entry["uri"])).write_bytes(b"[]")
    with pytest.raises(ValueError, match="snapshot digest"):
        render_release(["admission-blue"], [publication], store=store, manifest_key=MANIFEST_KEY)
