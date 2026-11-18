"""Preflight and dry-run share a literal Kubernetes parameter resource."""

from pathlib import Path

import pytest
import yaml


def test_preflight_preserves_the_scoped_resource_contract():
    from parameter_reader import read_parameters

    resource = yaml.safe_load((Path(__file__).parent / "fixtures" / "blue-publication.yaml")
                              .read_text(encoding="utf-8"))
    assert read_parameters("blue", resource) == {
        "namespace": "blue", "digest": "d" * 64, "images": [],
        "flows": [{"source": "reader", "destination": "web", "port": 443}]}
    with pytest.raises(ValueError, match="namespace"):
        read_parameters("green", resource)
