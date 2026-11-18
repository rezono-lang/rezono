"""Contract for a namespace parameter resource, derived from the admission decision."""

from pathlib import Path

import jsonschema
import pytest
import yaml


def test_namespace_publication_requires_typed_bounded_entries():
    path = Path(__file__).parent / "resources" / "publication-crd.yaml"
    crd = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert crd["apiVersion"] == "apiextensions.k8s.io/v1"
    assert crd["kind"] == "CustomResourceDefinition"
    spec = crd["spec"]
    assert spec["scope"] == "Namespaced"
    version, = [entry for entry in spec["versions"] if entry["storage"]]
    assert version["served"] is True
    schema = version["schema"]["openAPIV3Schema"]
    assert "spec" in schema["required"]
    body = schema["properties"]["spec"]
    validator = jsonschema.Draft4Validator(body)
    image = {"service": "web", "image": "registry.example.org/app@sha256:" + "a" * 64}
    flow = {"source": "reader", "destination": "web", "port": 443}
    good = {"digest": "d" * 64, "images": [image], "flows": [flow]}
    assert validator.is_valid(good)
    assert validator.is_valid(dict(good, images=[], flows=[]))
    for field in good:
        assert not validator.is_valid({k: v for k, v in good.items() if k != field})
    for bad in [dict(good, digest="D" * 64), dict(good, digest="d" * 63),
                dict(good, images=[{"service": "web"}]),
                dict(good, flows=[dict(flow, port="443")]),
                dict(good, flows=[dict(flow, port=65536)])]:
        assert not validator.is_valid(bad)
    for field, keys in [("images", {"service", "image"}),
                        ("flows", {"source", "destination", "port"})]:
        array = body["properties"][field]
        assert array["maxItems"] > 0
        assert array["x-kubernetes-list-type"] == "map"
        assert set(array["x-kubernetes-list-map-keys"]) == keys
