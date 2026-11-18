import pytest

from publication_wire_fixture import wire_case


def test_wire_publication_reaches_preflight():
    resource, _ = wire_case()
    from parameter_reader import read_parameters

    assert read_parameters("blue", resource) == {
        "namespace": "blue", "digest": "d" * 64, "images": [],
        "flows": [{"source": "reader", "destination": "web", "port": 443}]}
    with pytest.raises(ValueError, match="namespace"):
        read_parameters("green", resource)
