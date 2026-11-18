"""Transport authorization expectations from decisions/k8s-admission-transport.md."""

from copy import deepcopy
from pathlib import Path

import jsonschema
import pytest
import yaml


ROOT = Path(__file__).resolve().parent
ROW = {"source": "idp", "destination": "dns", "port": 53}


def publication(protocol):
    resource = yaml.safe_load((ROOT / "fixtures" / "blue-namespace-publication.yaml")
                              .read_text(encoding="utf-8"))
    resource["metadata"]["namespace"] = "platform"
    resource["spec"]["flows"] = [dict(ROW)] if protocol == "TCP" else []
    if protocol in ("UDP", "SCTP"):
        resource["spec"]["transportFlows"] = [dict(ROW, protocol=protocol)]
    return resource


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="Depends on the canonical publication reader. Extend k8s-admission/resources/publication-crd.yaml and parameter_reader.py together per decisions/k8s-admission-transport.md.")
def test_transport_publication_interchange():
    from parameter_reader import read_parameters

    crd = yaml.safe_load((ROOT / "resources" / "publication-crd.yaml").read_text(encoding="utf-8"))
    version, = [v for v in crd["spec"]["versions"] if v["storage"]]
    body = version["schema"]["openAPIV3Schema"]["properties"]["spec"]
    assert "transportFlows" in body["properties"]
    collection = body["properties"]["transportFlows"]
    assert collection["maxItems"] == body["properties"]["flows"]["maxItems"]
    keys = {"source", "destination", "protocol", "port"}
    assert collection["x-kubernetes-list-type"] == "map"
    assert set(collection["x-kubernetes-list-map-keys"]) == keys
    assert set(collection["items"]["required"]) == keys
    assert set(collection["items"]["properties"]) == keys
    resource = publication("TCP")
    rows = [dict(ROW, protocol=p) for p in ("UDP", "SCTP")]
    resource["spec"]["transportFlows"] = rows
    validator = jsonschema.Draft4Validator(body)
    assert validator.is_valid(resource["spec"])
    parsed = read_parameters("platform", resource)
    assert parsed["flows"] == [ROW]
    assert parsed["transportFlows"] == rows
    for bad in [ROW, dict(ROW, protocol="unknown"), dict(ROW, protocol="TCP"),
                dict(ROW, protocol="UDP", port=0)]:
        invalid = deepcopy(resource)
        invalid["spec"]["transportFlows"] = [bad]
        assert not validator.is_valid(invalid["spec"])
        with pytest.raises(ValueError):
            read_parameters("platform", invalid)
    for invalid_rows in [[rows[0], rows[0]], [dict(rows[0], typo=True)]]:
        invalid = deepcopy(resource)
        invalid["spec"]["transportFlows"] = invalid_rows
        with pytest.raises(ValueError):
            read_parameters("platform", invalid)


@pytest.mark.xfail(strict=True, reason="Depends on test_transport_publication_interchange, the shared NetworkPolicy renderer and managed preflight. Implement protocol-aware checks in k8s-admission/managed_network_policy.py per decisions/k8s-admission-transport.md.")
def test_rendered_transport_publication_matrix(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parent / "examples" / "platform"))
    from managed_network_policy import evaluate_network_policy
    from network_policy import render_network_policies
    from parameter_reader import read_parameters

    for requested in ("TCP", "UDP", "SCTP"):
        flow = dict(source="idp", destination="dns", protocol=requested, fromPort=53, toPort=53)
        bundle = render_network_policies("platform", [flow])
        for published in ("TCP", None, "UDP", "SCTP"):
            parameters = read_parameters("platform", publication(published))
            observed = []
            for manifest in bundle:
                spec = manifest["spec"]
                directions = tuple(sorted(spec["policyTypes"]))
                allowed = evaluate_network_policy(manifest, parameters)["allowed"]
                observed.append((directions, allowed))
            expected = requested == published
            assert sorted(observed) == [(("Egress",), expected), (("Egress", "Ingress"), True),
                                        (("Ingress",), expected)]
