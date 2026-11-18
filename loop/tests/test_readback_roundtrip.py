"""Recover original typed rows from two fields of one object."""

import pytest

from wire_fixtures import entry


def test_readback_roundtrip(monkeypatch):
    read_rows = entry(monkeypatch, "readback_roundtrip", "read_rows")
    ref = {"manifest": "m-a", "apiVersion": "v1", "kind": "ConfigMap", "namespace": "fixture", "name": "echo"}
    witness = {"relation": "service", "key": '["echo"]'}
    fields = [{"origin": "knowledge", "pointer": "/data/label", "column": "label", "type": "string", "witness": witness},
              {"origin": "knowledge", "pointer": "/data/name", "column": "name", "type": "string", "witness": witness}]
    obj = {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": "echo", "namespace": "fixture"},
           "data": {"name": "echo", "label": "fixture-echo"}}
    expected = [{"witness": witness, "row": {"name": "echo", "label": "fixture-echo"}}]
    assert read_rows({**ref, "fields": fields}, "m-a", obj) == expected
    with pytest.raises(ValueError):
        read_rows({**ref, "fields": [fields[0], dict(fields[1], column="label")]}, "m-a", obj)
